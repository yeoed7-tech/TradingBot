"""Structured rotating operational logs with redaction at the output boundary."""
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime,timezone
from pathlib import Path
from trading_bot.persistence.ledger import redact

class SafeJSONFormatter(logging.Formatter):
    def format(self,record):
        return json.dumps({'timestamp':datetime.fromtimestamp(record.created,timezone.utc).isoformat(),
           'level':record.levelname,'component':record.name,'event':getattr(record,'event','LOG'),
           'message':redact(record.getMessage()),'context':redact(getattr(record,'context',{}))},
           ensure_ascii=False,default=str)

def configure_log(path='logs/paper.jsonl',max_bytes=2_000_000,backup_count=5):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger('trading_bot.paper')
    logger.setLevel(logging.INFO)
    logger.propagate=False
    for handler in logger.handlers[:]:logger.removeHandler(handler);handler.close()
    handler=RotatingFileHandler(path,maxBytes=max_bytes,backupCount=backup_count,encoding='utf-8')
    handler.setFormatter(SafeJSONFormatter())
    logger.addHandler(handler)
    return logger
