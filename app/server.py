import os
import io
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pypdf import PdfReader

from chatkit.server import ChatKitServer, StreamingResult
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageItem,
    ThreadItemDoneEvent,
    AttachmentUploadDescriptor,
)

from app.postgres_store import PostgresStore
from app.attachments import (
    AttachmentContentStore,
    PostgresAttachmentStore,
)

AGENT_ID = "agent_7f94abb9ebf748da8b9674ea898a7fec80023bc7fe4b4a7cba"

ENVIRONMENT = {
    "type": "openai_hosted",
}

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024


def extract_text(content: bytes, mime_type: str) -> tuple[str, int | None]:
    """Estrae localmente il testo dai file TXT e PDF."""

    mime_type = mime_type.lower().split(";")[0].strip()

    if mime_type == "text/plain":
        try:
            return content.decode("utf-8-sig"), None
        except UnicodeDecodeError:
            return content.decode("cp1252", errors="replace"), None

    if mime_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(content))

            if reader.is_encrypted:
                raise HTTPException(
                    status_code=422,
                    detail="Il PDF è protetto da password.",
                )

            page_texts = [
                page.extract_text() or ""
                for page in reader.pages
            ]

            return "\n\n".join(page_texts), len(reader.pages)

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail="Impossibile leggere il PDF.",
            ) from exc

    raise HTTPException(
        status_code=415,
        detail="Sono supportati soltanto file TXT e PDF.",
    )


class RansiChatKitServer(ChatKitServer[dict]):
    def __init__(self):
        self.pg_store = PostgresStore()

        self.attachment_content_store = AttachmentContentStore(
            os.environ["DATABASE_URL"]
        )

        self.attachment_store = PostgresAttachmentStore(
            metadata_store=self.pg_store,
            content_store=self.attachment_content_store,
        )

        super().__init__(
            store=self.pg_store,
            attachment_store=self.attachment_store,
        )

        self.client = OpenAI()

    async def respond(self, thread, input_user_message, context):
        if input_user_message is None:
            return

        # Recupera il testo digitato dall'utente.
        text = "".join(
            content.text
            for content in input_user_message.content
            if hasattr(content, "text")
        )

        # Recupera e legge gli allegati associati al messaggio.
        attachment_sections = []

        for attachment in input_user_message.attachments:
            mime_type = attachment.mime_type.lower().split(";")[0].strip()

            if mime_type not in (
                "text/plain",
                "application/pdf",
            ):
                attachment_sections.append(
                    f"[Allegato non elaborato: {attachment.name}. "
                    f"Tipo non supportato: {attachment.mime_type}]"
                )
                continue

            _, file_content = await self.attachment_store.read_file(
                attachment_id=attachment.id,
                context=context,
            )

            extracted_text, page_count = extract_text(
                file_content,
                mime_type,
            )

            if extracted_text.strip():
                attachment_sections.append(
                    f"CONTENUTO DELL'ALLEGATO: {attachment.name}\n"
                    f"Tipo: {mime_type}\n"
                    + (
                        f"Pagine: {page_count}\n"
                        if page_count is not None
                        else ""
                    )
                    + "--- INIZIO TESTO ESTRATTO ---\n"
                    f"{extracted_text}\n"
                    "--- FINE TESTO ESTRATTO ---"
                )
            else:
                attachment_sections.append(
                    f"L'allegato {attachment.name} non contiene testo "
                    "estraibile. Se è un PDF scansionato, occorre OCR."
                )

        # Aggiunge il contenuto dei file al messaggio da inviare all'Agent.
        if attachment_sections:
            text += (
                "\n\n"
                "L'utente ha allegato i seguenti documenti. "
                "Usa il testo estratto come contesto per rispondere "
                "alla sua richiesta.\n\n"
                + "\n\n".join(attachment_sections)
            )

        session_id = await self.pg_store.get_agent_session_id(thread.id)

        if session_id is None:
            session = self.client.beta.agents.sessions.create(
                agent_id=AGENT_ID,
                environment=ENVIRONMENT,
            )

            session_id = session.id

            await self.pg_store.save_agent_session_id(
                thread.id,
                session_id,
            )

        full_text = ""

        with self.client.beta.agents.sessions.stream(
            session_id,
            input=text,
        ) as stream:
            for event in stream:
                if (
                    getattr(event, "type", "")
                    == "agent.session.turn.output_text.delta"
                ):
                    delta = getattr(event, "delta", "")

                    if delta:
                        full_text += delta

        assistant_item = AssistantMessageItem(
            id=f"msg_{uuid.uuid4().hex}",
            thread_id=thread.id,
            created_at=datetime.now(timezone.utc),
            content=[
                AssistantMessageContent(text=full_text)
            ],
        )

        yield ThreadItemDoneEvent(item=assistant_item)


app = FastAPI()

app.mount(
    "/public",
    StaticFiles(directory="public"),
    name="public",
)

chatkit_server = RansiChatKitServer()


@app.get("/")
async def home():
    return FileResponse("index.html")


@app.api_route(
    "/attachments/{attachment_id}/content",
    methods=["PUT", "POST"],
    name="upload_attachment",
)
async def upload_attachment(
    attachment_id: str,
    request: Request,
):
    content_type = request.headers.get("content-type", "").lower()

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        uploaded_file = form.get("file")

        if uploaded_file is None or not hasattr(uploaded_file, "read"):
            raise HTTPException(
                status_code=400,
                detail="Il form deve contenere il campo 'file'.",
            )

        content = await uploaded_file.read(MAX_ATTACHMENT_SIZE + 1)
    else:
        content = await request.body()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Contenuto del file mancante.",
        )

    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Dimensione massima: 10 MB.",
        )

    attachment = await chatkit_server.attachment_store.write_file(
        attachment_id=attachment_id,
        content=content,
        context={"request": request},
    )

    return attachment.model_dump(mode="json")


@app.get(
    "/attachments/{attachment_id}/content",
    name="download_attachment",
)
async def download_attachment(
    attachment_id: str,
    request: Request,
):
    attachment, content = (
        await chatkit_server.attachment_store.read_file(
            attachment_id=attachment_id,
            context={"request": request},
        )
    )

    return Response(
        content=content,
        media_type=attachment.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f'inline; filename="{attachment.name}"'
            ),
        },
    )


@app.get("/attachments/{attachment_id}/text")
async def extract_attachment_text(
    attachment_id: str,
    request: Request,
):
    attachment, content = (
        await chatkit_server.attachment_store.read_file(
            attachment_id=attachment_id,
            context={"request": request},
        )
    )

    extracted_text, page_count = extract_text(
        content,
        attachment.mime_type,
    )

    has_text = bool(extracted_text.strip())

    return {
        "filename": attachment.name,
        "mime_type": attachment.mime_type,
        "page_count": page_count,
        "character_count": len(extracted_text),
        "text_extracted": has_text,
        "text": extracted_text,
        "message": (
            "Testo estratto correttamente."
            if has_text
            else (
                "Non è stato trovato testo. "
                "Il PDF potrebbe essere una scansione e richiedere OCR."
            )
        ),
    }


@app.post("/chatkit")
async def chatkit(request: Request):
    result = await chatkit_server.process(
        await request.body(),
        context={"request": request},
    )

    if isinstance(result, StreamingResult):
        return StreamingResponse(
            result,
            media_type="text/event-stream",
        )

    return Response(
        content=result.json,
        media_type="application/json",
    )
