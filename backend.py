# app.py
from PyPDF2 import PdfReader  # Importing PdfReader for reading PDF files
from dotenv import load_dotenv  # Importing load_dotenv for loading environment variables
from langchain_text_splitters import RecursiveCharacterTextSplitter  # Importing RecursiveCharacterTextSplitter for text splitting
from langchain_openai.embeddings import OpenAIEmbeddings  # Importing OpenAIEmbeddings for embeddings
from langchain_community.vectorstores import DocArrayInMemorySearch  # Importing DocArrayInMemorySearch for vector storage
from langchain_core.output_parsers import StrOutputParser  # Importing StrOutputParser for output parsing
from langchain.prompts import ChatPromptTemplate  # Importing ChatPromptTemplate for chat prompts
from langchain_core.runnables import RunnablePassthrough  # Importing RunnablePassthrough for running tasks
from langchain_openai.chat_models import ChatOpenAI  # Importing ChatOpenAI for chat models
from openai import OpenAI
import tempfile
import whisper
from pytube import YouTube
import os
from control import *

import flask
from flask import Flask, request, jsonify
import dbcontroller

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/uploadYoutube', methods=['POST'])
def upload_youtube():
    # Check if the request has the 'youtube_link' parameter
    youtube_link = request.args.get("yt")
    # Check if the provided link is a valid YouTube link
    if not is_valid_youtube_link(youtube_link):
        return jsonify({'error': 'Invalid YouTube link provided'}), 400
    try:
        youtube = YouTube(youtube_link)
        audio = youtube.streams.filter(only_audio=True).first()
        whisper_model = whisper.load_model("base")
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = tempfile.TemporaryFile()
            temp = audio.download(output_path=tmpdir)
            # Use the Whisper model to transcribe the video
            transcribed_text = whisper_model.transcribe(temp, fp16=False)["text"].strip()
            db = dbcontroller.DBController()
            resourceId = request.args.get("resourceId")
            db.set_context(resourceId, transcribed_text)
            db.set_style(resourceId, "Bullet Points")
        return jsonify({'message': 'YouTube video uploaded and transcribed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def is_valid_youtube_link(link):
    # Check if the link starts with 'https://www.youtube.com/' and contains 'watch?v='
    if link.startswith('https://www.youtube.com/') and 'watch?v=' in link:
        return True
    return False

@app.route('/uploadAudio', methods=['POST'])
def upload_audio():
    load_dotenv()  # Loading environment variables
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    client = OpenAI(api_key=OPENAI_API_KEY)
    # Check if the request has the 'file' parameter
    #if 'file' not in request.files:
        #return jsonify({'error': 'No file part'}), 400
    audio_file = request.files['file']
    # Check if a file is selected
    if audio_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    try:
        transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        db = dbcontroller.DBController()
        resourceId = request.args.get("resourceId")
        db.set_context(resourceId, transcription)
        db.set_style(resourceId, "Bullet Points")
        return jsonify({'message': 'Audio file uploaded and transcribed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# TODO: read resourceId from user
@app.route('/uploadFile', methods=['POST'])
def upload_file():
    print("upload_file")
    #if 'file' not in request.files:
        #return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file:
        filename = file.filename
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename);
        file.save(path)
        notes_raw_text = get_pdf_text(path)
        db = dbcontroller.DBController();
        resourceId = request.args.get("resourceId");
        set_context_by_resourceid(resourceId, notes_raw_text);
        set_style_by_resourceid(resourceId, "Bullet Points")
        return jsonify({'message': 'File uploaded successfully', 'filename': filename})
    else:
        return jsonify({'error': 'File upload failed'}), 500

@app.route('/getNotes', methods=['GET'])
def getNotes():
    load_dotenv()  # Loading environment variables
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    model = ChatOpenAI(openai_api_key=OPENAI_API_KEY, model="gpt-3.5-turbo-0125")
    print("get_notes")
    db = dbcontroller.DBController();
    resourceId = request.args.get("resourceId");
    raw_text = db.get_context(resourceId)
    str_text = str(raw_text)
    notes_chunks = get_text_chunks(str_text)
    notes_vs = get_vectorstore(notes_chunks)
    style = db.get_style(resourceId)
    notes = generate_notes(notes_vs, style, model)
    return jsonify({'message': notes})


@app.route('/')
def get_home_html():
    return flask.render_template_string(
        '''
<!DOCTYPE html> <html lang="en"> <head> <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0"> <title>File Upload</title> </head> <body> <h1>Upload File</h1> <input type="file" id="fileInput"> <button onclick="uploadFile()">Upload</button>

 <script> function uploadFile() { const fileInput = document.getElementById('fileInput'); const file = fileInput.files[0];

 if (!file) { alert('Please select a file to upload'); return; }

 const formData = new FormData(); formData.append('file', file);

 fetch('/uploadFile?resourceId=e49462b3-737a-4aa9-8477-f5ab9d0bb687', { method: 'POST', body: formData }) .then(response => response.json()) .then(data => { console.log(data); alert(data.message); }) .catch(error => { console.error('Error:', error); alert('An error occurred while uploading the file'); }); } </script> </body> </html>
        '''
    )


def get_pdf_text(pdf_path):
    text = ""
    pdf_reader = PdfReader(pdf_path)
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

# Turns raw text into chunks
def get_text_chunks(raw_text):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size = 1000, chunk_overlap=20)
    chunks = text_splitter.split_text(raw_text)[:5]  # Limiting to 5 chunks
    return chunks

# Adds chunks to vector store
def get_vectorstore(text_chunks):
    embeddings = OpenAIEmbeddings()
    vectorstore = DocArrayInMemorySearch.from_texts(text_chunks, embeddings)
    return vectorstore

def generate_notes(contextVS, style, model):
    parser = StrOutputParser()
    template1 = """
        Generate structured notes for students based on given context, focusing on key topics and using the style provided.
        Ensure that you are only writing notes about the main topics of the lecture. Return the notes in HTML format, no newline characters only the body.

        Context: {context}
        Style: {style}
    """
    prompt1 = ChatPromptTemplate.from_template(template1)
    style_str = str(style)
    chain1 = (
        {"context": contextVS.as_retriever(), "style": RunnablePassthrough() }
        | prompt1
        | model 
        | parser
    )
    notes = chain1.invoke(style_str)
    return notes



if __name__ == '__main__':
    app.run(debug=True)