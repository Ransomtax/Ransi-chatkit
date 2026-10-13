import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

from chatkit.server import ChatKitServer, StreamingResult
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageItem,
    ThreadItemDoneEvent,
)

from app.postgres_store import PostgresStore
from app.attachments import AttachmentContentStore


AGENT_ID = "agent_7f94abb9ebf748da8b9674ea898a7fec80023bc7fe4b4a7cba"
ENVIRONMENT = {"type": "openai_hosted"}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
}


class RansiChatKitServer(ChatKitServer[dict]):
    def __init__(self):
        self.pg_store = PostgresStore()
        super().__init__(store=self.pg_store)
        self.client = OpenAI()

    async def respond(self, thread, input_user_message, context):
        if input_user_message is None:
            return

        text = "".join(
            content.text
            for content in input_user_message.content
            if hasattr(content, "text")
        )

        session_id = await self.pg_store.get_agent_session_id(thread.id)

        if session_id is None:
            session = self.client.beta.agents.sessions.create(
                agent_id=AGENT_ID,
                environment=ENVIRONMENT,
            )
            session_id = session.id
            await self.pg_store.save_agent_session_id(thread.id, session_id)

        full_text = ""

        with self.client.beta.agents.sessions.stream(
            session_id,
            input=text,
        ) as stream:
            for event in stream:
                if getattr(event, "type", "") == "agent.session.turn.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        full_text += delta

        assistant_item = AssistantMessageItem(
            id=f"msg_{uuid.uuid4().hex}",
            thread_id=thread.id,
            created_at=datetime.now(timezone.utc),
            content=[AssistantMessageContent(text=full_text)],
        )

        yield ThreadItemDoneEvent(item=assistant_item)


app = FastAPI()
app.mount("/public", StaticFiles(directory="public"), name="public")
chatkit_server = RansiChatKitServer()
attachment_store = AttachmentContentStore(os.environ["DATABASE_URL"])


@app.get("/")
async def home():
    return FileResponse("index.html")


@app.post("/attachments/upload")
async def upload_attachment(request: Request):
    content_type = request.headers.get("content-type", "")

    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="È richiesto un upload multipart.")

    form = await request.form()
    uploaded_file = form.get("file")

    if uploaded_file is None or not hasattr(uploaded_file, "read"):
        raise HTTPException(status_code=400, detail="File mancante.")

    if uploaded_file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Tipo di file non consentito.")

    content = await uploaded_file.read(MAX_ATTACHMENT_SIZE + 1)

    if not content:
        raise HTTPException(status_code=400, detail="Il file è vuoto.")

    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=413, detail="Dimensione massima: 10 MB.")

    attachment_id = f"att_{uuid.uuid4().hex}"

    await attachment_store.save(
        attachment_id=attachment_id,
        filename=os.path.basename(uploaded_file.filename or "allegato"),
        content_type=uploaded_file.content_type,
        content=content,
    )

    return {
        "id": attachment_id,
        "filename": os.path.basename(uploaded_file.filename or "allegato"),
        "content_type": uploaded_file.content_type,
        "size": len(content),
    }


@app.post("/chatkit")
async def chatkit(request: Request):
    result = await chatkit_server.process(await request.body(), context={})

    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")

    return Response(content=result.json, media_type="application/json")
