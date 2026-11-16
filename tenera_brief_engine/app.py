import os, json, sqlite3, hashlib
from datetime import datetime
from pathlib import Path
import gradio as gr

DATA = Path(os.getenv("TENERA_DATA_DIR", "/mnt/workspace/tenera_brief_engine"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "brief_engine.db"

def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init():
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT,collection TEXT,season TEXT,audience TEXT,channels TEXT,languages TEXT,source_text TEXT,created TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY,product_id TEXT,version INTEGER,status TEXT,brief TEXT,note TEXT,created TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY,product_id TEXT,category TEXT,feedback TEXT,created TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS proposals(id INTEGER PRIMARY KEY,title TEXT,proposal TEXT,source TEXT,status TEXT,created TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY,rule TEXT,source TEXT,created TEXT)")

def extract(files):
    out=[]; notes=[]
    for f in files or []:
        p=Path(f); ext=p.suffix.lower()
        try:
            if ext==".pdf":
                from pypdf import PdfReader
                t="\\n".join(x.extract_text() or "" for x in PdfReader(str(p)).pages)
            elif ext==".docx":
                from docx import Document
                d=Document(str(p)); t="\\n".join(x.text for x in d.paragraphs)
            elif ext in (".xlsx",".xls",".csv"):
                import pandas as pd
                if ext==".csv": t=pd.read_csv(p).to_string(index=False)
                else: t="\\n".join(f"[{k}]\\n{v.to_string(index=False)}" for k,v in pd.read_excel(p,sheet_name=None).items())
            elif ext in (".txt",".md"): t=p.read_text(encoding="utf-8",errors="ignore")
            elif ext in (".png",".jpg",".jpeg",".webp"):
                t=""; notes.append(f"{p.name}: 图片已接收；当前 MVP 尚未接入视觉识别。")
            else: t=""; notes.append(f"{p.name}: 暂不支持自动解析。")
            if t.strip(): out.append(f"\\n\\n### {p.name}\\n{t[:40000]}")
        except Exception as e: notes.append(f"{p.name}: 解析失败：{e}")
    return "\\n".join(out), "\\n".join(notes) or "文件解析完成"

def prompt_for(name,collection,season,audience,channels,languages,source,extra,rules):
    return f"""你是 TENERA 产品营销与 Creator Brief 专家。严格依据资料，不得编造尺寸、容量、材质认证、性能、市场数据；缺失信息标记【待确认】。
产品：{name}；系列：{collection}；季节：{season}
人群：{audience}；渠道：{channels}；语言：{languages}
已批准品牌规则：{rules or '暂无'}
补充说明：{extra or '无'}
源资料：{source or '暂无'}
请输出有效 JSON，包含：product_snapshot, source_gaps, positioning, product_story, audience_segments,
selling_points（区分事实/推断/待确认）, creator_profiles, content_pillars,
visual_directions（目标/场景/穿搭道具/镜头清单/必须展示）, video_hooks_en,
sample_script_en, photo_shotlist, creator_deliverables, do_and_dont, hashtags,
approval_items, optimization_hypotheses。每个内容方向必须有明确营销任务和可执行镜头。"""

def llm_call(prompt):
    key=os.getenv("LLM_API_KEY") or os.getenv("MODELSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base=os.getenv("LLM_BASE_URL"); model=os.getenv("LLM_MODEL")
    if not (key and base and model): return None,"未配置模型 API；请复制分析指令到 ChatGPT，生成 JSON 后导入。"
    try:
        from openai import OpenAI
        client=OpenAI(api_key=key,base_url=base)
        r=client.chat.completions.create(model=model,messages=[{"role":"user","content":prompt}],temperature=0.4)
        return r.choices[0].message.content,"模型调用成功"
    except Exception as e: return None,f"模型调用失败：{e}"

def save_version(pid,obj,status="draft",note=""):
    with conn() as c:
        v=c.execute("SELECT COALESCE(MAX(version),0)+1 n FROM versions WHERE product_id=?",(pid,)).fetchone()["n"]
        c.execute("INSERT INTO versions(product_id,version,status,brief,note,created) VALUES(?,?,?,?,?,?)",
                  (pid,v,status,json.dumps(obj,ensure_ascii=False),note,datetime.utcnow().isoformat()))
    return v

def create(name,collection,season,audience,channels,languages,files,extra):
    if not name.strip(): return "请填写产品名称","","",""
    source,note=extract(files)
    pid=hashlib.sha1((name+datetime.utcnow().isoformat()).encode()).hexdigest()[:10]
    with conn() as c:
        c.execute("INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?)",(pid,name,collection,season,audience,channels,languages,source,datetime.utcnow().isoformat()))
        rules="\\n".join(r["rule"] for r in c.execute("SELECT rule FROM rules"))
    prompt=prompt_for(name,collection,season,audience,channels,languages,source,extra,rules)
    result,msg=llm_call(prompt)
    if result:
        try:
            s=result.find("{"); e=result.rfind("}"); obj=json.loads(result[s:e+1])
            save_version(pid,obj,note="自动生成首版")
            display=json.dumps(obj,ensure_ascii=False,indent=2)
        except Exception: display=result+"\\n\\n注意：结果不是标准 JSON，请修正后导入。"
    else: display="尚未生成模型结果。请复制下方指令到 ChatGPT，生成 JSON 后在「导入 ChatGPT 结果」中保存。"
    return f"产品 ID：{pid}\\n{note}\\n{msg}",pid,display,prompt

def choices():
    with conn() as c: rows=c.execute("SELECT id,name,collection FROM products ORDER BY created DESC").fetchall()
    return [(f"{r['name']} · {r['collection'] or '未分系列'} · {r['id']}",r["id"]) for r in rows]

def import_result(pid,raw,note):
    if not pid: return "请先选择产品",gr.update(choices=choices())
    try: obj=json.loads(raw)
    except Exception as e: return f"JSON 格式错误：{e}",gr.update(choices=choices())
    v=save_version(pid,obj,note=note or "ChatGPT 导入")
    return f"已保存 V{v}（草稿）",gr.update(choices=choices())

def feedback(pid,cat,txt):
    if not pid or not txt.strip(): return "请选择产品并填写反馈",gr.update(choices=choices())
    with conn() as c: c.execute("INSERT INTO feedback(product_id,category,feedback,created) VALUES(?,?,?,?)",(pid,cat,txt,datetime.utcnow().isoformat()))
    return "反馈已记录。请交由 ChatGPT 分析；通用规则变更须进入审批队列。",gr.update(choices=choices())

def versions(pid):
    if not pid:return "请选择产品"
    with conn() as c: rows=c.execute("SELECT version,status,note,created,brief FROM versions WHERE product_id=? ORDER BY version DESC",(pid,)).fetchall()
    return "\\n\\n".join([f"### V{x['version']} · {x['status']}\\n{x['created']} · {x['note']}\\n```json\\n{x['brief']}\\n```" for x in rows]) or "暂无版本"

def propose(title,txt,src):
    if not title.strip() or not txt.strip(): return "请填写规则名称和内容"
    with conn() as c:c.execute("INSERT INTO proposals(title,proposal,source,status,created) VALUES(?,?,?,'pending',?)",(title,txt,src,datetime.utcnow().isoformat()))
    return "已提交待审批"

def proposals():
    with conn() as c: rows=c.execute("SELECT * FROM proposals ORDER BY id DESC").fetchall()
    return "\\n\\n".join([f"**#{r['id']} {r['title']}** · {r['status']}\\n{r['proposal']}" for r in rows]) or "暂无待审批提案"

def decide(pid,decision):
    if not str(pid).isdigit():return "请输入提案编号",proposals()
    with conn() as c:
        r=c.execute("SELECT * FROM proposals WHERE id=?",(int(pid),)).fetchone()
        if not r:return "未找到提案",proposals()
        c.execute("UPDATE proposals SET status=? WHERE id=?",(decision,int(pid)))
        if decision=="approved":c.execute("INSERT INTO rules(rule,source,created) VALUES(?,?,?)",(r["proposal"],f"proposal:{pid}",datetime.utcnow().isoformat()))
    return f"已标记为 {decision}",proposals()

init()
with gr.Blocks(title="TENERA AI Brief Engine",theme=gr.themes.Soft()) as demo:
    gr.Markdown("# TENERA AI Brief Engine\\n**Product → Strategy → Creator Brief → Feedback → Approved Brand Learning**\\n半自动机制：内容草稿可自动生成；品牌级规则和策略变更须人工审批。")
    with gr.Tabs():
        with gr.Tab("01 新品建档"):
            with gr.Row():
                name=gr.Textbox(label="产品名称 *",placeholder="Ballerina Polka Dot Shoulder Bag")
                collection=gr.Textbox(label="系列",value="Ballerina Collection")
                season=gr.Textbox(label="季节/波段",placeholder="26AW")
            with gr.Row():
                audience=gr.Textbox(label="目标人群")
                channels=gr.Textbox(label="渠道",value="Instagram Reels / TikTok / REDnote")
                languages=gr.Textbox(label="输出语言",value="中文策略 + 英文达人 Brief")
            files=gr.File(label="产品资料 PDF/DOCX/XLSX/CSV/TXT/图片",file_count="multiple",type="filepath")
            extra=gr.Textbox(label="补充说明",lines=3)
            go=gr.Button("分析资料并生成首版 Brief",variant="primary")
            status=gr.Textbox(label="状态"); pid=gr.Textbox(label="产品 ID")
            brief=gr.Code(label="Brief 草稿",language="json")
            prompt=gr.Textbox(label="复制到 ChatGPT 的分析指令",lines=12)
            go.click(create,[name,collection,season,audience,channels,languages,files,extra],[status,pid,brief,prompt])
        with gr.Tab("02 导入 ChatGPT 结果"):
            p1=gr.Dropdown(label="产品",choices=choices())
            raw=gr.Code(label="粘贴 ChatGPT 返回的 JSON",language="json")
            note=gr.Textbox(label="版本说明",value="ChatGPT 优化版本")
            b1=gr.Button("保存为新版本",variant="primary"); s1=gr.Textbox(label="状态")
            b1.click(import_result,[p1,raw,note],[s1,p1])
        with gr.Tab("03 反馈与版本"):
            p2=gr.Dropdown(label="产品",choices=choices())
            cat=gr.Dropdown(label="反馈类型",choices=["产品定位","核心卖点","视觉方向","视频脚本","达人匹配","内容表现","品牌规范","其他"],value="视觉方向")
            fb=gr.Textbox(label="反馈内容",lines=5)
            b2=gr.Button("记录反馈"); s2=gr.Textbox(label="状态")
            b2.click(feedback,[p2,cat,fb],[s2,p2])
            p3=gr.Dropdown(label="查看产品版本",choices=choices()); b3=gr.Button("查看版本"); vout=gr.Markdown()
            b3.click(versions,p3,vout)
        with gr.Tab("04 Brand DNA 审批"):
            t=gr.Textbox(label="规则提案名称"); body=gr.Textbox(label="建议规则内容",lines=4); src=gr.Textbox(label="来源产品 ID（可选）")
            b4=gr.Button("提交审批"); s4=gr.Textbox(label="状态"); b4.click(propose,[t,body,src],s4)
            b5=gr.Button("刷新提案"); pout=gr.Markdown(value=proposals()); b5.click(proposals,outputs=pout)
            with gr.Row():
                proposal_id=gr.Number(label="提案编号",precision=0); decision=gr.Radio(["approved","rejected"],value="approved",label="审批决定")
            b6=gr.Button("确认审批"); s6=gr.Textbox(); b6.click(decide,[proposal_id,decision],[s6,pout])
        with gr.Tab("05 使用说明"):
            gr.Markdown("""- 支持 PDF、DOCX、XLSX、CSV、TXT 文本抽取；图片目前只登记，不做视觉识别。
- 可配置 OpenAI-compatible 模型接口：`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
- 未配置 API 时，通过 ChatGPT 提示词复制/JSON 导入桥接。
- ModelScope Studio 与 ChatGPT 消费者会话不会自动互通；直接 API 协作需独立 API 凭证。
- 当前 MVP 尚未提供登录权限、云端对象存储、自动备份、PDF/DOCX 导出。
- 数据默认写入 `/mnt/workspace/tenera_brief_engine`；正式使用前请验证持久化和备份。
- API Key 必须放在 Studio 密钥管理中，不要写入代码或仓库。""")
if __name__=="__main__": demo.queue().launch(server_name="0.0.0.0",server_port=int(os.getenv("PORT","7860")))
