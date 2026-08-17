# agent.py
import os
import asyncio
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    ConversationItemAddedEvent,
    JobContext,
    WorkerOptions,
    APIConnectOptions,
    cli,
    llm,
    log,
)
from livekit.agents.voice.agent_session import SessionConnectOptions
from livekit.plugins import deepgram, elevenlabs, silero, openai as lk_openai

# Our custom modules
from tools import JarvisTools
from memory import MemoryManager

from DREAMS_SYSTEM_PROMPT import DREAMS_SYSTEM_PROMPT

load_dotenv()

# Increase the LiveKit LLM API timeout for local Ollama requests.
# The default timeout is too short for some local model completion responses.
LIVEKIT_LLM_TIMEOUT = float(os.getenv("LIVEKIT_LLM_TIMEOUT", "60.0"))

ENABLE_LIVEKIT_TOOLS = os.getenv("ENABLE_LIVEKIT_TOOLS", "false").strip().lower() in ("1", "true", "yes")

logger = log.logger
memory = MemoryManager()


async def entrypoint(ctx: JobContext):
    session_id = f"chat_session:{ctx.room.name}"

    # --- RESTORE MEMORY ---
    initial_ctx = llm.ChatContext()
    past_session = await memory.restore_session(session_id)
    if past_session:
        print("🔄 RECOVERING SESSION FROM REDIS!")
        for msg in past_session:
            initial_ctx.add_message(role=msg["role"], content=msg["text"])
    else:
        initial_ctx.add_message(
            role="system",
            content=DREAMS_SYSTEM_PROMPT,
        )

    # --- BUILD SESSION WITH LOCAL OLLAMA GEMMA ---
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=lk_openai.LLM(
            model="llama3.2:1b",  # <-- Match the exact name here!
            api_key="ollama",
            base_url="http://127.0.0.1:11434/v1",
            temperature=0.3,
        ),
        tts=elevenlabs.TTS(),
        conn_options=SessionConnectOptions(
            llm_conn_options=APIConnectOptions(timeout=LIVEKIT_LLM_TIMEOUT)
        ),
    )

    agent_tools = [JarvisTools()] if ENABLE_LIVEKIT_TOOLS else []
    if not ENABLE_LIVEKIT_TOOLS:
        logger.warning(
            "LiveKit tools are disabled for the selected local Ollama model. "
            "Set ENABLE_LIVEKIT_TOOLS=true only if your model/provider supports function calling."
        )

    agent = Agent(
        instructions="You are Dreams, a helpful and concise voice assistant.",
        chat_ctx=initial_ctx,
        tools=agent_tools,
    )
    
    # --- LATENCY MONITORING (STRUCTURED METRICS) ---
    @session.on("metrics_collected")
    def on_metrics_collected(event):
        metrics = getattr(event, "metrics", event)
        metric_name = getattr(metrics, "type", None) or type(metrics).__name__
        duration = getattr(metrics, "duration", None)
        status = getattr(metrics, "status", None)

        logger.info(
            "latency metric collected",
            extra={
                "metric_name": metric_name,
                "duration": duration,
                "status": status,
            },
        )

    # --- CONVERSATION HOOKS (STRUCTURED LOGS) ---
    @session.on("conversation_item_added")
    def on_conversation_item_added(event: ConversationItemAddedEvent):
        item = event.item
        if item.role == "user":
            logger.info("user spoke", extra={"text": item.text_content})
            asyncio.create_task(
                memory.backup_session(session_id, session.history.items)
            )
        elif item.role == "assistant":
            logger.info("dreams spoke", extra={"text": item.text_content})
            asyncio.create_task(
                memory.backup_session(session_id, session.history.items)
            )

    # --- GRACEFUL DISCONNECT ---
    @ctx.room.on("disconnected")
    def on_disconnected():
        logger.info("user disconnected, starting graceful cleanup", extra={"session_id": session_id})
        asyncio.create_task(
            memory.save_fact(f"Conversation finished at session: {session_id}")
        )
        logger.info("cleanup complete, shutting down worker")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    print(f"Agent joined room: {ctx.room.name}")

    await session.start(room=ctx.room, agent=agent)

    # --- GREETING ---
    await session.generate_reply(
        instructions="Say: All systems online. Local model loaded. How can I help?",
        allow_interruptions=True,
    )

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))