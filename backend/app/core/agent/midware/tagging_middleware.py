from langchain.agents.middleware import AgentMiddleware


class TaggingMiddleware(AgentMiddleware):
    priority = 100  # 最低优先级，标签添加在最后执行

    def __init__(self, tag: str):
        self.tag = tag

    def wrap_model_call(self, request, handler):
        return handler(request.override(tags=[self.tag]))
