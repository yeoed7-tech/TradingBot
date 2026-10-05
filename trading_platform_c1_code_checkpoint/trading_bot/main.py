import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
from trading_bot.config.settings import Settings
from trading_bot.data.market_data import synthetic_data,MarketDataEngine
from trading_bot.strategies import create_strategy
from trading_bot.backtest.engine import BacktestEngine
from trading_bot.backtest.validation import walk_forward,grid_search,chronological_split
from trading_bot.analytics.report import write_report,compare


def main(argv=None):
    parser=argparse.ArgumentParser(description='Modular research and public-data paper trading (no live orders)')
    parser.add_argument('command',choices=['demo','backtest','compare','optimize','walk-forward','split','paper','monitor','live'])
    parser.add_argument('--config',default=None)
    parser.add_argument('--strategy')
    parser.add_argument('--symbol')
    parser.add_argument('--timeframe')
    parser.add_argument('--duration',type=float,default=180)
    parser.add_argument('--data',help='CSV OHLCV; mandatory except demo')
    parser.add_argument('--out',default='reports/run')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--grid',default='config/grid.json')
    parser.add_argument('--train-bars',type=int,default=300)
    parser.add_argument('--test-bars',type=int,default=100)
    parser.add_argument('--train-end',default='2023-01-01')
    parser.add_argument('--test-end',default='2024-01-01')
    args=parser.parse_args(argv)
    if args.command == 'live':
        parser.error('Live trading is not implemented; no exchange order can be submitted')
    settings=Settings.load(args.config or ('config/paper_upbit.toml' if args.command=='paper' else 'config/default.toml'))
    if args.command=='monitor':
        from trading_bot.api.app import create_app
        import uvicorn
        uvicorn.run(create_app(settings.persistence.database_url,settings.persistence.account),
                    host=args.host,port=args.port)
        return
    if args.command=='paper':
        import asyncio
        from trading_bot.paper_trading.runner import run_public_paper
        values=settings.model_dump()
        if args.symbol: values['paper_trading']['symbol']=args.symbol
        if args.timeframe: values['paper_trading']['timeframe']=args.timeframe
        if args.strategy:
            if args.strategy!=values['strategy']['name']: values['strategy']['params']={}
            values['strategy']['name']=args.strategy
        settings=Settings.model_validate(values)
        strategy=create_strategy(settings.strategy.name,settings.strategy.params)
        result=asyncio.run(run_public_paper(settings,strategy,args.out,args.duration))
        print(json.dumps(result,default=str,indent=2))
        if result.get('error') or result['status']=='FAILED': raise SystemExit(2)
        return
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    if args.command=='demo':
        frame=synthetic_data()
        frame.to_csv(out/'synthetic_ohlcv.csv',index=False)
        source='SYNTHETIC deterministic fixture (seed=42), NOT actual crypto history'
    else:
        if not args.data: parser.error('--data is required')
        frame=MarketDataEngine.from_csv(args.data,settings.bar_seconds).frame
        source='User CSV SHA256='+hashlib.sha256(Path(args.data).read_bytes()).hexdigest()
    if args.command in {'demo','compare'}:
        results={name:BacktestEngine(settings).run(frame,create_strategy(name),name) for name in ['ema_cross','rsi','breakout']}
        print(compare(results,out,source).to_string())
    elif args.command=='backtest':
        result=BacktestEngine(settings).run(frame,create_strategy(settings.strategy.name,settings.strategy.params),settings.strategy.name)
        print(json.dumps(write_report(result,out,source),indent=2))
    elif args.command=='split':
        parts=chronological_split(frame,args.train_end,args.test_end)
        for name,part in parts.items(): part.to_csv(out/f'{name}.csv',index=False)
        print({k:len(v) for k,v in parts.items()})
    else:
        grid=json.loads(Path(args.grid).read_text())
        if args.command=='optimize':
            result=grid_search(frame,settings,settings.strategy.name,grid,settings.strategy.params)
        else:
            result=walk_forward(frame,settings,settings.strategy.name,grid,args.train_bars,args.test_bars,settings.strategy.params)
        (out/'validation.json').write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps(result,indent=2))
    print(f'Output: {out.resolve()}')

if __name__=='__main__': main()
