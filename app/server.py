import uuid
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from openai import OpenAI

from chatkit.server import ChatKitServer, StreamingResult
from chatkit.store import Store
from chatkit.types import (
    AssistantMessageContent,
    AssistantMessageItem,
    Page,
    ThreadItemDoneEvent,
)


AGENT_ID = "agent_7f94abb9ebf748da8b9674ea898a7fec80023bc7fe4b4a7cba"

ENVIRONMENT = {
    "type": "openai_hosted",
}


class MemoryStore(Store[dict]):

    def __init__(self):
        self.threads = {}
        self.items = {}

    def generate_thread_id(self, context):
        return f"thread_{uuid.uuid4().hex}"

    async def load_thread(self, thread_id, context):
        return self.threads[thread_id]

    async def save_thread(self, thread, context):
        self.threads[thread.id] = thread

    async def load_thread_items(
        self,
        thread_id,
        after,
        limit,
        order,
        context,
    ):
        items = self.items.get(thread_id, [])

        if order == "desc":
            items = list(reversed(items))

        return Page(
            data=items[:limit],
            has_more=False,
        )

    async def save_attachment(self, attachment, context):
        pass

    async def load_attachment(self, attachment_id, context):
        raise KeyError(attachment_id)

    async def delete_attachment(self, attachment_id, context):
        pass

    async def load_threads(
        self,
        limit,
        after,
        order,
        context,
    ):
        threads = list(self.threads.values())

        if order == "desc":
            threads = list(reversed(threads))

        return Page(
            data=threads[:limit],
            has_more=False,
        )

    async def add_thread_item(
        self,
        thread_id,
        item,
        context,
    ):
        self.items.setdefault(thread_id, []).append(item)

    async def save_item(
        self,
        thread_id,
        item,
        context,
    ):
        items = self.items.setdefault(thread_id, [])

        for i, existing in enumerate(items):
            if existing.id == item.id:
                items[i] = item
                return

        items.append(item)

    async def load_item(
        self,
        thread_id,
        item_id,
        context,
    ):
        for item in self.items.get(thread_id, []):
            if item.id == item_id:
                return item

        raise KeyError(item_id)

    async def delete_thread(
        self,
        thread_id,
        context,
    ):
        self.threads.pop(thread_id, None)
        self.items.pop(thread_id, None)

    async def delete_thread_item(
        self,
        thread_id,
        item_id,
        context,
    ):
        self.items[thread_id] = [
            item
            for item in self.items.get(thread_id, [])
            if item.id != item_id
        ]


class RansiChatKitServer(ChatKitServer[dict]):

    def __init__(self):
        super().__init__(store=MemoryStore())
        self.client = OpenAI()
        self.sessions = {}

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

        session_id = self.sessions.get(thread.id)

        if session_id is None:
            session = self.client.beta.agents.sessions.create(
                agent_id=AGENT_ID,
                environment=ENVIRONMENT,
            )

            session_id = session.id
            self.sessions[thread.id] = session_id

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
                AssistantMessageContent(
                    text=full_text,
                )
            ],
        )

        yield ThreadItemDoneEvent(
            item=assistant_item,
        )


app = FastAPI()

from fastapi.staticfiles import StaticFiles

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