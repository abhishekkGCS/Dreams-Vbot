

"""
The Theory (How Function Calling Works):
JSON Schemas: Gemini cannot actually browse the web or run Python code. Instead, we give Gemini a JSON document that describes the tools we have available (e.g., "I have a tool called get_time").
The Routing Decision: When you ask a question, Gemini makes a routing decision: "Can I answer this from my training data, OR should I output a JSON string asking the server to run a tool?"
Tool Execution: If Gemini outputs a tool request, the LiveKit framework intercepts it, pauses the audio, runs your actual Python function, takes the result (like the current time), injects it back into the context window, and tells Gemini: "Here is the data, now formulate a spoken response for the user."
LiveKit makes this incredibly easy. You just write normal Python classes and use the @llm.function_tool decorator. LiveKit handles generating the JSON schemas and executing the routing automatically
"""



"""
The Theory: How AI "Remembers"
LLMs can't natively remember anything between sessions. To solve this, we use two techniques:

Short-Term Memory (Redis): If you disconnect from the room and reconnect 5 minutes later, you shouldn't have to introduce yourself again. We serialize the ChatContext (the array of messages) and save it to Redis with a 1-hour expiration. When you connect, we pull it from Redis and hand it back to the LiveKit Agent.
Long-Term Memory (MongoDB): We cannot shove 6 months of conversation logs into the LLM context window—it would be too slow and cost a fortune in API tokens.
The Solution: We give Jarvis Memory Tools. We teach him to automatically extract facts. If you say, "By the way, my name is Alex," Jarvis uses a tool to save { "name": "Alex" } to MongoDB.
The Injection: Next week, when you connect to a new room, we query MongoDB before Jarvis says hello, and we inject those facts directly into his system prompt: "You are talking to Alex. He likes Python."
"""


# import asyncio
# import json
# from datetime import datetime


# class JarvisTools:
#     def __init__(self):
#         self.fake_mongo_db = {
#             "preferences": [],
#             "notes": [],
#             "projects": {},
#         }

#     async def get_time(self):
#         print("🛠️ Tool Executed: get_time")
#         now = datetime.now().strftime("%I:%M %p on %A, %B %d")
#         return f"The current time is {now}"

#     async def search_web(self, query: str):
#         print(f"🛠️ Tool Executed: search_web | Query: {query}")
#         await asyncio.sleep(1)
#         return f"Here is the top result for '{query}': OpenAI and Google just released new multimodal voice models."

#     async def calculator(self, equation: str):
#         print(f"🛠️ Tool Executed: calculator | Equation: {equation}")
#         try:
#             return f"The answer is {eval(equation)}"
#         except Exception:
#             return "I could not calculate that."

#     async def save_user_fact(self, fact: str):
#         print(f"🧠 MEMORY SAVED: {fact}")
#         self.fake_mongo_db["preferences"].append(fact)
#         return "Fact saved successfully to long-term memory."

#     async def recall_user_facts(self):
#         print("🧠 MEMORY RECALLED")
#         if not self.fake_mongo_db["preferences"]:
#             return "No past memories found."
#         return json.dumps(self.fake_mongo_db["preferences"])

#     async def create_project(self, project_name: str):
#         print(f"📁 PROJECT CREATED: {project_name}")
#         if project_name in self.fake_mongo_db["projects"]:
#             return f"Project '{project_name}' already exists."

#         self.fake_mongo_db["projects"][project_name] = []
#         return f"Project '{project_name}' created successfully."

#     async def add_task(self, project_name: str, task_name: str, deadline: str, priority: str):
#         print(f"✅ TASK ADDED -> Project: {project_name} | Task: {task_name} | Priority: {priority} | Due: {deadline}")

#         if project_name not in self.fake_mongo_db["projects"]:
#             return f"Error: Project '{project_name}' does not exist. Tell the user to create it first."

#         new_task = {
#             "name": task_name,
#             "deadline": deadline,
#             "priority": priority,
#             "status": "pending",
#         }
#         self.fake_mongo_db["projects"][project_name].append(new_task)
#         return f"Task added to project '{project_name}' successfully."

#     async def update_task_status(self, project_name: str, task_name: str, status: str):
#         print(f"🔄 TASK UPDATED -> Project: {project_name} | Task: {task_name} | Status: {status}")

#         if project_name not in self.fake_mongo_db["projects"]:
#             return f"Project '{project_name}' not found."

#         for task in self.fake_mongo_db["projects"][project_name]:
#             if task_name.lower() in task["name"].lower():
#                 task["status"] = status
#                 return f"Task '{task_name}' marked as {status}."

#         return f"Could not find task '{task_name}' in project '{project_name}'."

#     async def list_tasks(self, project_name: str):
#         print(f"📋 LISTING TASKS FOR: {project_name}")

#         if project_name not in self.fake_mongo_db["projects"]:
#             return f"Project '{project_name}' does not exist."

#         tasks = self.fake_mongo_db["projects"][project_name]
#         if not tasks:
#             return f"There are no tasks in project '{project_name}'."

#         return json.dumps(tasks)




# tools.py
import json
import asyncio
from datetime import datetime
from livekit.agents import llm, log
from duckduckgo_search import DDGS # Real web search
from memory import MemoryManager # Real Mongo database manager

logger = log.logger

class JarvisTools(llm.Toolset):
    def __init__(self):
        super().__init__(id="jarvis_tools")
        # Instantiate memory connection (connects to real Mongo & Redis)
        self.memory = MemoryManager()

    # --- SYSTEM & UTILITIES ---

    @llm.function_tool(description="Get the current time and date.")
    async def get_time(self):
        logger.info("executing tool: get_time")
        now = datetime.now().strftime("%I:%M %p on %A, %B %d")
        return f"The current time is {now}"

    @llm.function_tool(description="Search the web for real-time news, facts, or information.")
    async def search_web(self, query: str):
        logger.info("executing tool: search_web", extra={"query": query})
        try:
            async with DDGS() as ddgs:
                results = [r async for r in ddgs.text(query, max_results=3)]
                if not results:
                    return f"I couldn't find any information on '{query}'."

                formatted_results = "Raw Web Data:\n"
                for i, res in enumerate(results):
                    formatted_results += f"\nResult {i+1}: {res['title']}\nSnippet: {res['body']}\n"
                return formatted_results
        except Exception as e:
            logger.error("search_web tool failed", exc_info=e)
            return "I am having trouble accessing the internet right now."

    @llm.function_tool(description="Calculate math equations.")
    async def calculator(self, equation: str):
        logger.info("executing tool: calculator", extra={"equation": equation})
        try:
            import ast

            expr = ast.parse(equation, mode="eval")

            allowed_nodes = {
                ast.Expression,
                ast.Constant,
                ast.BinOp,
                ast.UnaryOp,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.Pow,
                ast.Mod,
                ast.USub,
                ast.UAdd,
                ast.FloorDiv,
                ast.LShift,
                ast.RShift,
                ast.BitXor,
                ast.BitAnd,
                ast.BitOr,
                ast.Invert,
            }

            for node in ast.walk(expr):
                if type(node) not in allowed_nodes:
                    raise ValueError("Unsupported expression")

            result = eval(compile(expr, filename="<ast>", mode="eval"), {}, {})
            return f"The answer is {result}"
        except Exception:
            return "I could not calculate that."

    # --- MEMORY TOOLS (REAL MONGODB) ---

    @llm.function_tool(description="Save an important fact or preference about the user to long-term memory.")
    async def save_user_fact(self, fact: str):
        logger.info("executing tool: save_user_fact", extra={"fact": fact})
        await self.memory.save_fact(fact)
        return "Fact saved successfully to long-term memory."

    @llm.function_tool(description="Look up past notes or facts about the user.")
    async def recall_user_facts(self):
        logger.info("executing tool: recall_user_facts")
        facts = await self.memory.get_facts()
        if not facts:
            return "No past memories found."
        return json.dumps(facts)

    # --- PROJECT MANAGER TOOLS (REAL MONGODB) ---

    @llm.function_tool(description="Create a new empty project workspace.")
    async def create_project(self, project_name: str):
        logger.info("executing tool: create_project", extra={"project_name": project_name})
        collection = self.memory.db["projects"]
        
        # Check if project exists in real Mongo
        existing = await collection.find_one({"name": project_name})
        if existing:
            return f"Project '{project_name}' already exists."

        await collection.insert_one({"name": project_name, "tasks": []})
        return f"Project '{project_name}' created successfully in MongoDB."

    @llm.function_tool(description="Add a new task to an existing project with a deadline and priority.")
    async def add_task(
        self,
        project_name: str,
        task_name: str,
        deadline: str,
        priority: str,
    ):
        logger.info("executing tool: add_task", extra={"project": project_name, "task": task_name})
        collection = self.memory.db["projects"]
        
        project = await collection.find_one({"name": project_name})
        if not project:
            return f"Error: Project '{project_name}' does not exist. Tell the user to create it first."

        new_task = {
            "name": task_name,
            "deadline": deadline,
            "priority": priority,
            "status": "pending"
        }
        
        # Push task into the project's array in MongoDB
        await collection.update_one({"name": project_name}, {"$push": {"tasks": new_task}})
        return f"Task added to project '{project_name}' successfully."

    @llm.function_tool(description="Update the status of a specific task.")
    async def update_task_status(
        self,
        project_name: str,
        task_name: str,
        status: str,
    ):
        logger.info("executing tool: update_task_status", extra={"project": project_name, "task": task_name, "status": status})
        collection = self.memory.db["projects"]
        
        # Update the task status inside the array
        result = await collection.update_one(
            {"name": project_name, "tasks.name": task_name},
            {"$set": {"tasks.$.status": status}}
        )
        
        if result.modified_count > 0:
            return f"Task '{task_name}' marked as {status}."
        return f"Could not find task '{task_name}' in project '{project_name}'."

    @llm.function_tool(description="List all tasks for a specific project.")
    async def list_tasks(
        self,
        project_name: str,
    ):
        logger.info("executing tool: list_tasks", extra={"project": project_name})
        collection = self.memory.db["projects"]
        
        project = await collection.find_one({"name": project_name})
        if not project:
            return f"Project '{project_name}' does not exist."

        tasks = project.get("tasks", [])
        if not tasks:
            return f"There are no tasks in project '{project_name}'."

        return json.dumps(tasks)