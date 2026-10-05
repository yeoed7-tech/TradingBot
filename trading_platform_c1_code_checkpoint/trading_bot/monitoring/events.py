import json
from collections import deque
from pathlib import Path

class EventJournal:
    def __init__(self,max_events=None): self.events=deque(maxlen=max_events) if max_events else [];self.max_events=max_events
    def record(self,event,**payload):
        self.events.append({'event':event,**payload})
    def save(self,path):
        path=Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('w',encoding='utf-8') as f:
            for event in self.events: f.write(json.dumps(event,default=str,ensure_ascii=False)+'\n')
