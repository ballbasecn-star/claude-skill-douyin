#!/usr/bin/env python3
"""自动拆解：只拆爆款。

爆款门槛（相对 + 绝对地板，两个都要满足）：
    点赞 >= FLOOR（绝对地板，挡噪声）
    且 点赞 >= MULT × 该博主中位数（相对，抓这个号自己的突围款）

用法：
    deconstruct.py --author "西门聪明蛋XD"            # dry-run：看门槛命中哪些 + 抽一条试拆(不写库)
    deconstruct.py --author "西门聪明蛋XD" --write     # 真拆并写回库(只补有转录、且还没拆的爆款)
    deconstruct.py --author "X" --floor 2000 --mult 2  # 调门槛

拆解走国产大模型（SiliconFlow，.env 里 SILICONFLOW_API_KEY）。六维：选题角度/钩子/结构/爆点·数据证据/CTA/可抄点。
"""
import sys, os, json, argparse, statistics, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from dotenv import dotenv_values
from lib.feishu_client import FeishuClient

FIELDS = ['选题角度', '钩子', '结构', '爆点·数据证据', 'CTA', '可抄点']
SF_URL = 'https://api.siliconflow.cn/v1/chat/completions'
SF_MODEL = os.environ.get('SF_MODEL', 'Qwen/Qwen2.5-72B-Instruct')

PROMPT = """你是对标拆解分析师，服务 AI 自媒体博主「林克AI实战录」（后端转型的 AI 实战派 / 帮普通人用上 AI / 程序员真实复盘 / KPI=涨粉+进群）。
下面是一条爆款短视频的转录文案 + 数据。按六维拆解，只输出一个 JSON 对象（键必须是这六个中文键），每个值简洁、有信息量、说人话：
- 选题角度：切的什么角度/痛点/人群
- 钩子：前3秒或标题怎么勾人（引原句+点手法：反转/暴论/成果诱惑/痛点）
- 结构：口播骨架（分几段、怎么递进）
- 爆点·数据证据：结合 赞{like}/评{comment} 判断驱动类型（收藏干货型=高赞评比 / 争议型 / 共鸣型 / 励志型）+ 为什么爆
- CTA：结尾引导（关注/评论/领资料/私信/无）
- 可抄点：★林克能怎么抄这一条（结合他定位，给一条可落地的）

标题：{title}
点赞 {like}，评论 {comment}
转录文案：
{transcript}

只输出 JSON，不要任何解释、不要 markdown 代码块。"""


def _parse_json(txt: str) -> dict:
    txt = txt.strip()
    txt = re.sub(r'^```(?:json)?|```$', '', txt, flags=re.MULTILINE).strip()
    try:
        return json.loads(txt)
    except Exception:
        m = re.search(r'\{.*\}', txt, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    raise ValueError('LLM 未返回合法 JSON')


def llm_deconstruct(v: dict, key: str) -> dict:
    body = {
        'model': SF_MODEL,
        'messages': [{'role': 'user', 'content': PROMPT.format(**v)}],
        'temperature': 0.3,
    }
    r = requests.post(SF_URL, headers={'Authorization': f'Bearer {key}',
                      'Content-Type': 'application/json'}, json=body, timeout=120)
    data = r.json()
    if 'choices' not in data:
        raise RuntimeError(f'SiliconFlow 返回异常: {json.dumps(data, ensure_ascii=False)[:200]}')
    return _parse_json(data['choices'][0]['message']['content'])


def fetch_author_records(fc, base, table, author):
    items, pt = [], None
    while True:
        params = {'field_names': json.dumps(['视频ID', '标题', '转录文案', '点赞数', '评论数'] + FIELDS, ensure_ascii=False), 'page_size': 500}
        if pt:
            params['page_token'] = pt
        body = {'filter': {'conjunction': 'and', 'conditions': [{'field_name': '作者', 'operator': 'is', 'value': [author]}]}}
        r = requests.post(f'https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{table}/records/search',
                          headers=fc._headers, params=params, json=body, timeout=20).json()
        items += r['data'].get('items', [])
        pt = r['data'].get('page_token')
        if not pt:
            break
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--author', required=True)
    ap.add_argument('--floor', type=int, default=2000, help='绝对地板(点赞)')
    ap.add_argument('--mult', type=float, default=2.0, help='相对倍数(× 博主中位数)')
    ap.add_argument('--write', action='store_true', help='真写回库(默认 dry-run)')
    a = ap.parse_args()

    v = dotenv_values('.env')
    fc = FeishuClient(v['FEISHU_APP_ID'], v['FEISHU_APP_SECRET'])
    base, table, key = v['FEISHU_BASE_TOKEN'], v['FEISHU_TABLE_ID'], v.get('SILICONFLOW_API_KEY', '')
    g = lambda f, k: fc._extract_text(f.get(k, ''))

    items = fetch_author_records(fc, base, table, a.author)
    likes = [f['fields'].get('点赞数', 0) or 0 for f in items]
    med = statistics.median(likes) if likes else 0
    thr = max(a.floor, a.mult * med)
    print(f'【{a.author}】{len(items)} 条 · 点赞中位数={med:.0f} · 门槛=max({a.floor}, {a.mult}×{med:.0f})={thr:.0f}')

    hot = [it for it in items if (it['fields'].get('点赞数', 0) or 0) >= thr]
    todo = [it for it in hot if g(it['fields'], '转录文案').strip() and not g(it['fields'], '可抄点').strip()]
    print(f'过门槛(爆款)={len(hot)} 条 · 其中有转录且未拆解、待拆={len(todo)} 条\n')
    for it in sorted(hot, key=lambda x: x['fields'].get('点赞数', 0) or 0, reverse=True):
        f = it['fields']
        st = '已拆' if g(f, '可抄点').strip() else ('缺转录' if not g(f, '转录文案').strip() else '★待拆')
        print(f"  赞{f.get('点赞数',0):>6} [{st}] {g(f,'标题')[:26]}")

    if not a.write:
        sample = next((it for it in hot if g(it['fields'], '转录文案').strip()), None)
        if sample and key:
            f = sample['fields']
            vv = {'title': g(f, '标题'), 'like': f.get('点赞数', 0), 'comment': f.get('评论数', 0), 'transcript': g(f, '转录文案')[:3500]}
            print(f'\n--- 抽样试拆(不写库)：{vv["title"][:22]} ---')
            try:
                res = llm_deconstruct(vv, key)
                for kk in FIELDS:
                    print(f'  ▸ {kk}：{str(res.get(kk, "")).strip()[:110]}')
            except Exception as e:
                print('  LLM 出错：', e)
        print('\n(这是 dry-run；加 --write 才真拆并写回库)')
        return

    # 真写回
    if not key:
        print('❌ .env 缺 SILICONFLOW_API_KEY'); return
    ok = fail = 0
    for i, it in enumerate(todo, 1):
        f = it['fields']
        vv = {'title': g(f, '标题'), 'like': f.get('点赞数', 0), 'comment': f.get('评论数', 0), 'transcript': g(f, '转录文案')[:3500]}
        print(f'[{i}/{len(todo)}] 拆：{vv["title"][:22]}', flush=True)
        try:
            res = llm_deconstruct(vv, key)
            fields = {k: str(res.get(k, '')).strip() for k in FIELDS if str(res.get(k, '')).strip()}
            up = requests.put(f'https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{table}/records/{it["record_id"]}',
                              headers=fc._headers, json={'fields': fields}, timeout=20).json()
            if up.get('code') == 0:
                print(f'   ✅ 写回 {len(fields)} 字段', flush=True); ok += 1
            else:
                print(f'   ❌ 写回失败 {up.get("code")} {up.get("msg")}', flush=True); fail += 1
        except Exception as e:
            print(f'   ❌ {e}', flush=True); fail += 1
        time.sleep(1)
    print(f'\n=== 完成：拆并写回 {ok} / 失败 {fail} / 待拆 {len(todo)} ===')


if __name__ == '__main__':
    raise SystemExit(main())
