class ToolRouter:
    def __init__(self): self.handlers = {}
    def register_tool(self, name, handler): self.handlers[name] = handler
    async def execute_tool(self, name, arguments):
        if name not in self.handlers: raise ValueError(f"Unknown tool: {name}")
        return await self.handlers[name](**arguments)
