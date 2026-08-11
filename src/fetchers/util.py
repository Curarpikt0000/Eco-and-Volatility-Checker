"""通用抓取工具：带真 header 的 HTTP、Jina Reader 绕反爬、硬超时。"""
import concurrent.futures
import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}
PER_FETCH_TIMEOUT = 30


def http_get(url, headers=None, timeout=25, as_json=False):
    """带浏览器 header 的 GET。返回 (status_code, text_or_json) 或 (None, err)。"""
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout)
        if as_json:
            return r.status_code, (r.json() if r.status_code == 200 else r.text)
        return r.status_code, r.text
    except Exception as e:
        return None, f"ERR {type(e).__name__}: {e}"


def jina_get(url, timeout=60, retries=2):
    """用 Jina Reader 绕反爬 (r.jina.ai)。返回 markdown 文本或 None。
    重站渲染慢，加重试 + 更长超时 + 纯文本头(更快)。"""
    import time
    hdr = {"User-Agent": UA, "X-Return-Format": "text"}
    for attempt in range(retries + 1):
        try:
            r = requests.get("https://r.jina.ai/" + url, headers=hdr, timeout=timeout)
            if r.status_code == 200 and len(r.text) > 100:
                return r.text
        except Exception:
            pass
        if attempt < retries:
            time.sleep(4 * (attempt + 1))
    return None


def with_timeout(fn, *args, timeout=PER_FETCH_TIMEOUT, **kwargs):
    """给任意抓取函数套硬超时(防慢站挂起)。超时返回 None。"""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return None
    except Exception:
        return None
    finally:
        ex.shutdown(wait=False)
