"""Reproducible TQQQ research; no broker credentials or order network paths."""
import argparse
from bisect import bisect_right
from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import subprocess

import exchange_calendars
import pandas as pd

from trading_bot.analytics.metrics import performance
from trading_bot.core.portfolio.precision import floor_step, tick_price
from trading_bot.strategies.laoer_tqqq import Parameters, VERSION
from .history import fetch_inputs, load_fx, load_prices
from .simulation import ResearchAccount

D = Decimal
INITIAL = D("10000")


def summarize(rows, trades=None, first_day=None):
    eq = pd.DataFrame(rows)
    eq.index = pd.to_datetime(eq.date)
    # Include opening cash for first-session costs and drawdowns.
    equity = pd.concat([pd.DataFrame({"equity":[float(INITIAL)]},
                      index=[eq.index[0]-pd.Timedelta(seconds=1)]),eq[["equity"]]])
    metrics = performance(equity,trades,bar_seconds=365.25*86400/252)
    peak = INITIAL
    peak_day = first_day or date.fromisoformat(rows[0]["date"])
    max_days, recoveries, in_drawdown = 0, [], False
    for row in rows:
        day = date.fromisoformat(row["date"])
        if row["equity"] >= peak:
            if in_drawdown:
                recoveries.append((day-peak_day).days)
            peak,peak_day,in_drawdown = row["equity"],day,False
        else:
            in_drawdown = True
            max_days = max(max_days,(day-peak_day).days)
    if recoveries:
        max_days = max(max_days,max(recoveries))
    metrics.update(maximum_underwater_days=max_days,
                   average_recovery_days=sum(recoveries)/len(recoveries) if recoveries else None)
    return metrics


def fx_result(net, first, last, fx, cost):
    dates = sorted(fx)
    def rate(d):
        idx = bisect_right(dates,d)-1
        if idx<0 or (d-dates[idx]).days>7:
            raise ValueError("FX history missing or stale")
        return fx[dates[idx]]
    initial_rate, end_rate = rate(first), rate(last)
    gross = (1+D(str(net)))*end_rate/initial_rate
    after = gross*(1-cost)/(1+cost)
    return {"initial_krw_per_usd":initial_rate,"end_krw_per_usd":end_rate,
            "fx_return":end_rate/initial_rate-1,"krw_return_before_fx_cost":gross-1,
            "krw_converted_return":after-1,"fx_cost_return_drag":gross-after}


def run(bars, config, fx):
    a = ResearchAccount(INITIAL,config)
    for bar in bars:
        a.step(bar)
    end = a.rows[-1]
    trades = pd.DataFrame(a.portfolio.trades)
    stats = summarize(a.rows,trades)
    cycles = a.cycles+([a.cycle_record(bars[-1],completed=False)] if a.cycle else [])
    stats.update(fees=end["fees"],realized_pnl=end["realized"],unrealized_pnl=end["unrealized"],
        distributions=a.dividends, modeled_buy_slippage=sum(f.slippage for f in a.fills.values()),
        capital_utilization=sum(r["utilization"] for r in a.rows)/len(a.rows),
        maximum_capital_utilization=max(r["utilization"] for r in a.rows),
        turnover=sum(f.price*f.quantity for f in a.fills.values())/(sum(r["equity"] for r in a.rows)/len(a.rows)),
        cash_exhaustion_count=sum(bool(c["exhausted_at"]) for c in cycles),
        budget_threshold_counts={str(i):sum(c["usage"]>=D(i)/100 for c in cycles) for i in (50,75,100)},
        max_post_exhaustion_drop=min((c["max_post_exhaustion_drop"] for c in cycles),default=D(0)),
        max_exhausted_days=max((c["exhausted_days"] for c in cycles),default=0),
        longest_cycle_days=max((c["calendar_days"] for c in cycles),default=0),
        completed_cycles=len(a.cycles),unfinished_cycle_pnl=(end["unrealized"] +
            (a.portfolio.positions["TQQQ"].realized if end["quantity"] else D(0))+
            (a.dividends-a.cycle.distribution_start if a.cycle else D(0))),
        fill_count=a.portfolio.fill_count,killed=a.risk.killed)
    return {**stats,**fx_result(stats["total_return"],bars[0].day,bars[-1].day,fx,config.fx_cost)},a,cycles


def benchmark(bars, config, allocation):
    cash,quantity,distributions = INITIAL,D(0),D(0)
    rows=[]
    for index,bar in enumerate(bars):
        if index==0 and allocation:
            price=tick_price(bar.open*(1+config.slip),config.tick,True)
            quantity=floor_step(INITIAL*allocation/(price*(1+config.fee)),1)
            cash-=quantity*price*(1+config.fee)
        elif index:
            quantity*=bar.split
            distributions+=quantity*bar.dividend
        rows.append({"date":str(bar.day),"equity":cash+quantity*bar.close+distributions})
    return summarize(rows)


def study(data, out, config):
    data,out=Path(data),Path(out)
    calendar=exchange_calendars.get_calendar("XNAS",start="2010-01-01",end="2027-01-01")
    bars=load_prices(data/"TQQQ","TQQQ",calendar)
    qqq_by_day={b.day:b for b in load_prices(data/"QQQ","QQQ",calendar)}
    fx=load_fx(data/"FX")
    windows={"full":bars,"development":[b for b in bars if b.day.year<=2018],
             "validation":[b for b in bars if 2019<=b.day.year<=2021],
             "holdout":[b for b in bars if b.day.year>=2022]}
    if any(len(w)<200 for w in windows.values()):
        raise ValueError("insufficient data for frozen splits")
    report={"strategy":VERSION,"parameters":config.__dict__,"config_hash":config.digest,
            "inputs":{name:sha256((data/name).read_bytes()).hexdigest() for name in ("TQQQ","QQQ","FX")},
            "source_commit":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
            "tracked_diff_sha256":sha256(subprocess.check_output(["git","diff","HEAD","--","trading_bot"])).hexdigest(),
            "windows":{}}
    out.mkdir(parents=True,exist_ok=True)
    for name,window in windows.items():
        result,a,cycles=run(window,config,fx)
        gross,_,_=run(window,replace(config,fee=D(0),slip=D(0),fx_cost=D(0)),fx)
        report["windows"][name]={"start":str(window[0].day),"end":str(window[-1].day),
            "sessions":len(window),"net":result,"gross_no_trade_cost_rerun":gross,
            "TQQQ_BH":benchmark(window,config,D(1)),"QQQ_BH":benchmark(
                [qqq_by_day[b.day] for b in window],config,D(1)),
            "TQQQ_BH_allocation_matched":benchmark(window,config,config.allocation),
            "cash":benchmark(window,config,D(0))}
        if name=="full":
            pd.DataFrame(a.rows).to_csv(out/"equity.csv",index=False)
            pd.DataFrame(cycles).to_csv(out/"cycles.csv",index=False)
            pd.DataFrame(a.portfolio.fills).to_csv(out/"fills.csv",index=False)
    folds=[]
    for year in range(2015,bars[-1].day.year+1):
        test=[b for b in bars if b.day.year==year]
        context=[b for b in bars if year-3<=b.day.year<year]
        result,_,_=run(test,config,fx)
        folds.append({"context_start":str(context[0].day),"context_end":str(context[-1].day),
                      "test_start":str(test[0].day),"test_end":str(test[-1].day),
                      "test":result})
    report["walk_forward_fixed_parameters"]=folds
    positive=sum(f["test"]["total_return"]>0 for f in folds)/len(folds)
    report["positive_fold_share"]=positive
    hold=report["windows"]["holdout"]["net"]
    report["verdict"]="RESEARCH FURTHER" if (
        hold["cagr"]>0 and hold["max_drawdown"]>=-.35 and positive>=.60) else "REJECT"
    report["development_sensitivity"]=[]
    for name, values in {"slices":[30,50],"target":[D(".08"),D(".12")],"interval":[2,3],
                         "allocation":[D(".5"),D(".75")],"generous":[D(".05"),D(".15")],
                         "fee":[D(".001"),D(".002")]}.items():
        for value in values:
            score,_,_=run(windows["development"],replace(config,**{name:value}),fx)
            report["development_sensitivity"].append({"parameter":name,"value":value,"metrics":score})
    report["stress_windows"]={}
    for name, start, end in [
        ("low_vol_bull_2017","2017-01-01","2018-01-01"),
        ("mixed_2015","2015-01-01","2016-01-01"),
        ("covid_crash","2020-02-19","2020-03-24"),
        ("long_recovery_2022_24","2022-01-01","2025-01-01"),
        ("bull_2023_24","2023-01-01","2025-01-01")]:
        window=[b for b in bars if start<=str(b.day)<end]
        stats,_,_=run(window,config,fx)
        report["stress_windows"][name]={"start":start,"end_exclusive":end,"net":stats}
    (out/"summary.json").write_text(json.dumps(report,indent=2,default=str,allow_nan=False)+"\n")
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data",type=Path,required=True)
    p.add_argument("--out",type=Path,default=Path("reports/tqqq_laoer"))
    p.add_argument("--fetch-before",type=date.fromisoformat)
    p.add_argument("--fee",default=".0005")
    p.add_argument("--slippage",default=".0005")
    p.add_argument("--fx-cost",default="0")
    a=p.parse_args()
    if a.fetch_before:
        fetch_inputs(a.data,a.fetch_before)
    print(study(a.data,a.out,Parameters(fee=a.fee,slip=a.slippage,fx_cost=a.fx_cost))["verdict"])


if __name__=="__main__":
    main()
