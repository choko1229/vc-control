from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def fmt_jst(dt: datetime) -> str:
    return dt.astimezone(JST).strftime("%-m月%-d日 %H:%M")


def fmt_duration(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    out = []
    if h:
        out.append(f"{h}時間")
    if m or (h and s):
        out.append(f"{m}分")
    out.append(f"{s}秒")
    return "".join(out)
