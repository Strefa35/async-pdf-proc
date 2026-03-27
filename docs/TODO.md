# The task
Create an async document processing application. Users can upload one or more PDF files via a website that you’ll create. After some time, a per-page content and summarization of these files (one summary per each uploaded file) is displayed on the page. Application accepts any PDF and parses it to a text (or markdown if possible) using one of the following methods (allow user to choose between those methods):
- PyPDF - this won’t extract markdown, only text, but that’s fine.
- Google Gemini 2.5 Flash (use its free tier to provision API key) - you can use it for parsing of a PDF file to markdown

The backend should take the uploaded PDF, the desired parser from above, then parse the contents, and finally output markdown-formatted text and a summary of that text. Tech stack to use:
- Python 3.12+ with FastAPI
- Redis v7+
- Docker Compose
- PyPDF for simple PDF parsing
- Google Gemini 2.5 Flash for advanced parsing into the markdown and summarization
- Javascript or Typescript with React (or Next.JS) for the Frontend


# Implementation details:
- Start with the backend part, we’re less interested in Frontend (nice to have, but not a must).
- The API should take the uploaded PDF, and the desired parser value - PyPDF, Google Gemini Flash or Mistral - and then parse and store in Redis the resulting markdown and a summary of that text.
- For the summary, just use Gemini Flash 2.5.
- It is acceptable to demo your application using Postman or CURL instead of full frontend, if you didn’t have time to complete it.
- Use Redis Streams feature of Redis as a queue to asynchronously process uploaded documents
- You can use any public PDFs of your choice as a sample to demo
- On Frontend you can use API polling, websockets or SSE to display summarization results once they’re ready (but ok to demo with Postman or CURL).
- Wrap all application components in Docker Compose


# Helpful:
- Google Gemini MODEL_ID = "gemini-2.5-flash"
- If some requirements are not clear, then make reasonable assumptions and move forward with implementation
- If you're stuck on some technicality, then feel free to work around it any way you can, and proceed forward with implementation


# The priority of implemented features (top to bottom: from most important to “nice to have”):
- Backend application, able to run and serve concurrent API requests
- Document upload and processing with PyPDF
- Async Redis queue with Streams
- Summarization via Google Gemini
- Document processing via Mistral OCR
- Frontend

---

**Async PDF Processor** v.0.0.1 · 26 March 2026 · Code author: Arkadiusz Czerwinski