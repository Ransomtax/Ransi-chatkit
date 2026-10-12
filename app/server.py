
import uuid
from datetime import datetime

from fastapi import FastAPI, Request, Response
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


AGENT_ID = "agent_7f94abb9ebf748da8b9674ea898a7fec80023bc7fe4b4a7cba"

ENVIRONMENT = {
    "type": "openai_hosted",
}


class RansiChatKitServer(ChatKitServer[dict]):
    def __init__(self):
        self.pg_store = PostgresStore()
        super().__init__(store=self.pg_store)
        self.client = OpenAI()

    async def respond(
        self,
        thread,
        input_user_message,
        context,
    ):
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
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        full_text += delta

        assistant_item = AssistantMessageItem(
            id=f"msg_{uuid.uuid4().hex}",
            thread_id=thread.id,
            created_at=datetime.now(),
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


@app.post("/chatkit")
async def chatkit(request: Request):
    result = await chatkit_server.process(
        await request.body(),
        context={},
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
