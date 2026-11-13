"""Explicit read-only account probe; offline master verification is the default."""
import argparse
from hashlib import sha256
from pathlib import Path
import json
from urllib.request import urlopen

from .broker import MeritzBrokerAdapter
from .market import Instrument, MASTER_URL
from .transport import MeritzError, ReadOnlyTransport


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--master",type=Path,required=True)
    p.add_argument("--download-master",action="store_true")
    p.add_argument("--read-account",action="store_true")
    a=p.parse_args()
    if a.download_master:
        with urlopen(MASTER_URL,timeout=15) as r:
            data=r.read(4_000_001)
        if len(data)>4_000_000:
            raise SystemExit("master file too large")
        a.master.parent.mkdir(parents=True,exist_ok=True)
        tmp=a.master.with_suffix(".tmp")
        tmp.write_bytes(data)
        Instrument.from_master(tmp,"TQQQ")
        tmp.replace(a.master)
    i=Instrument.from_master(a.master,"TQQQ")
    result={"symbol":i.symbol,"market":i.market,"vendor":i.vendor,
            "master_sha256":sha256(a.master.read_bytes()).hexdigest(),
            "api_authenticated":False,"order_write_calls":0}
    if a.read_account:
        with ReadOnlyTransport() as t:
            b=MeritzBrokerAdapter(t)
            try:
                t.token()
                b.get_cash()
                b.get_foreign_cash()
                b.get_positions()
                quote=b.get_quote(i)
                if quote.currency!="USD":
                    raise ValueError("unexpected currency")
                result.update(api_authenticated=True,account_reads_ok=True,quote_ok=True,
                              currency=quote.currency,quote_delayed=quote.delayed,
                              trade_rules_confirmed=quote.rules_confirmed,sell_only=quote.sell_only)
            except (MeritzError,ValueError,KeyError,TypeError):
                raise SystemExit("read-only probe failed; no order was submitted") from None
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
