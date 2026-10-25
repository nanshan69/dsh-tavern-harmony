#!/usr/bin/env python3
"""PubMed / Europe PMC / ClinicalTrials.gov 检索与文献核对工具。

用法（在工作目录或任意目录均可，相对路径按工作目录解析）：

  python scripts/pubmed.py search --query '"photobiomodulation"[tiab] AND osteoporosis[tiab]' --retmax 50
  python scripts/pubmed.py search --query '...' --years 2018-2026 --out literature/检索结果_新.csv
  python scripts/pubmed.py fetch  --pmids 12345678,23456789 --out literature/关键文献.json
  python scripts/pubmed.py oa     --pmid 12345678 --outdir fulltext
  python scripts/pubmed.py ctgov  --query "photobiomodulation osteoporosis" --out literature/注册试验.csv
  python scripts/pubmed.py verify --file docs/方案.md
  python scripts/pubmed.py cite   --pmids 12345678,34567890

环境变量（可选）：
  NCBI_API_KEY     NCBI 密钥，限速从 3 次/秒提高到 10 次/秒
  NCBI_EMAIL       向 NCBI 表明身份（推荐填写真实邮箱）
  DSHM_HTTP_VERIFY_SSL=1  严格校验证书（默认关闭，端侧自签证书链会报错）

输出默认写到工作目录下的 literature/。
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

# 保证无论用 runpy 还是 python3 script.py 运行，都能找到同目录的 _util.py
sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import ROOT, fmt_p, http_get, md_table, resolve_path, write_csv, write_json  # noqa: E402

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"

PMID_RE = re.compile(r"PMID[:：\s]*([0-9]{6,9})")
DOI_RE = re.compile(r"10\.[0-9]{4,9}/[-._;()/:A-Za-z0-9]+")
CITE_RE = re.compile(r"\[(\d{1,3})\]")

# NCBI 礼貌参数与限速
NCBI_PARAMS = {}
if "NCBI_EMAIL" in __import__("os").environ:
    NCBI_PARAMS["email"] = __import__("os").environ["NCBI_EMAIL"]
if "NCBI_API_KEY" in __import__("os").environ:
    NCBI_PARAMS["api_key"] = __import__("os").environ["NCBI_API_KEY"]
SLEEP = 0.12 if "NCBI_API_KEY" in __import__("os").environ else 0.36


# ---------------------------------------------------------------- PubMed 基础
def esearch(term: str, retmax: int = 50, mindate: str | None = None,
            maxdate: str | None = None, sort: str = "relevance",
            datetype: str = "pdat") -> tuple[int, list[str]]:
    params = {"db": "pubmed", "term": term, "retmode": "json", "retmax": str(retmax),
              "sort": sort, **NCBI_PARAMS}
    if mindate:
        params.update({"mindate": mindate, "datetype": datetype})
    if maxdate:
        params["maxdate"] = maxdate
    data = __import__("json").loads(http_get(EUTILS + "esearch.fcgi", params=params))
    result = data["esearchresult"]
    return int(result.get("count", 0)), result.get("idlist", [])


def esummary(ids: list[str]) -> dict:
    if not ids:
        return {}
    data = __import__("json").loads(http_get(
        EUTILS + "esummary.fcgi",
        params={"db": "pubmed", "retmode": "json", "id": ",".join(ids), **NCBI_PARAMS}))
    return data.get("result", {})


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def fetch_articles(ids: list[str]) -> list[dict]:
    """用 efetch 抓取完整题录 + 摘要（每批 100 条）。"""
    out: list[dict] = []
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        xml = http_get(EUTILS + "efetch.fcgi", params={
            "db": "pubmed", "retmode": "xml", "id": ",".join(batch), **NCBI_PARAMS})
        root = ET.fromstring(xml)
        for art in root.findall(".//PubmedArticle"):
            rec: dict = {}
            rec["pmid"] = _text(art.find(".//PMID"))
            ids_el = art.findall(".//ArticleIdList/ArticleId")
            rec["doi"] = next((_text(e) for e in ids_el if e.get("IdType") == "doi"), "")
            rec["pmc"] = next((_text(e) for e in ids_el if e.get("IdType") == "pmc"), "")
            rec["title"] = _text(art.find(".//ArticleTitle")).rstrip(".")
            rec["journal"] = _text(art.find(".//Journal/Title")) or _text(
                art.find(".//Journal/ISOAbbreviation"))
            rec["journal_abbr"] = _text(art.find(".//Journal/ISOAbbreviation"))
            pubdate = art.find(".//JournalIssue/PubDate")
            year = _text(pubdate.find("Year")) if pubdate is not None else ""
            if not year and pubdate is not None:
                year = re.findall(r"\d{4}", _text(pubdate.find("MedlineDate")))[:1]
                year = year[0] if isinstance(year, list) and year else ""
            rec["year"] = year
            rec["volume"] = _text(art.find(".//JournalIssue/Volume"))
            rec["issue"] = _text(art.find(".//JournalIssue/Issue"))
            rec["pages"] = _text(art.find(".//Pagination/MedlinePgn"))
            rec["pubtype"] = "; ".join(_text(e) for e in art.findall(".//PublicationTypeList/PublicationType"))
            authors: list[str] = []
            for a in art.findall(".//AuthorList/Author"):
                last = _text(a.find("LastName"))
                initials = _text(a.find("Initials"))
                collective = _text(a.find("CollectiveName"))
                if last:
                    authors.append(f"{last} {initials}".strip())
                elif collective:
                    authors.append(collective)
            rec["authors"] = authors
            rec["first_author"] = authors[0] if authors else ""
            abstract_parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                label = ab.get("Label")
                txt = _text(ab)
                abstract_parts.append(f"{label}: {txt}" if label else txt)
            rec["abstract"] = "\n".join(abstract_parts)
            rec["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/"
            if rec["doi"]:
                rec["doi_url"] = f"https://doi.org/{rec['doi']}"
            out.append(rec)
        time.sleep(SLEEP)
    return out


# ---------------------------------------------------------------- Europe PMC
def epmc_by_pmid(pmid: str) -> dict:
    data = __import__("json").loads(http_get(EPMC + "search", params={
        "query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "pageSize": 1}))
    hits = data.get("resultList", {}).get("result", [])
    return hits[0] if hits else {}


def epmc_fulltext_text(pmcid: str) -> str | None:
    try:
        xml = http_get(EPMC + f"{pmcid}/fullTextXML")
        root = ET.fromstring(xml)
        parts = []
        for el in root.iter():
            if el.tag in ("p", "title", "sec", "abstract"):
                txt = _text(el)
                if txt:
                    parts.append(txt)
        return "\n\n".join(parts)
    except Exception:
        return None


def cmd_oa(args) -> int:
    outdir = resolve_path(args.outdir, "fulltext")
    outdir.mkdir(parents=True, exist_ok=True)
    pmid = args.pmid
    meta = epmc_by_pmid(pmid)
    pmcid = meta.get("pmcid") or ""
    title = meta.get("title", "")
    year = meta.get("pubYear", "")
    if not pmcid:
        print(f"[未找到 OA 全文] PMID {pmid} 没有 PMC 编号：{title}")
        print(f"  PubMed: https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        return 1
    text = epmc_fulltext_text(pmcid)
    if not text or len(text) < 500:
        print(f"[抓取失败] PMID {pmid} / {pmcid} 全文 XML 为空（可能不在 OA 子集）")
        print(f"  PMC: https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/")
        return 1
    target = outdir / f"{pmid}_{year or 'noyear'}.txt"
    header = f"# PMID {pmid} | {pmcid} | {title}\n# 来源: Europe PMC fullTextXML\n\n"
    target.write_text(header + text, encoding="utf-8")
    print(f"[完成] {target}（{len(text)} 字符）")
    return 0


# ---------------------------------------------------------------- ClinicalTrials.gov
def cmd_ctgov(args) -> int:
    fields = ",".join([
        "NCTId", "BriefTitle", "OverallStatus", "StudyType", "Phase",
        "StartDate", "PrimaryCompletionDate", "EnrollmentCount", "Condition",
        "InterventionName", "LeadSponsorName", "LastUpdatePostDate"])
    data = __import__("json").loads(http_get(CTGOV, params={
        "query.term": args.query, "pageSize": str(args.retmax), "format": "json",
        "fields": fields}))
    rows = []
    for st in data.get("studies", []):
        ps = st.get("protocolSection", {})
        ident = ps.get("identificationModule", {})
        status = ps.get("statusModule", {})
        design = ps.get("designModule", {})
        arms = ps.get("armsInterventionsModule", {})
        sponsor = ps.get("sponsorCollaboratorsModule", {})
        cond = ps.get("conditionsModule", {})
        rows.append({
            "NCT": ident.get("nctId", ""),
            "title": ident.get("briefTitle", ""),
            "status": status.get("overallStatus", ""),
            "type": design.get("studyType", ""),
            "phase": "; ".join(design.get("phases", []) or []),
            "start": (status.get("startDateStruct") or {}).get("date", ""),
            "primary_completion": (status.get("primaryCompletionDateStruct") or {}).get("date", ""),
            "enrollment": (design.get("enrollmentInfo") or {}).get("count", ""),
            "condition": "; ".join(cond.get("conditions", []) or []),
            "intervention": "; ".join((i.get("name") or "") for i in (arms.get("interventions") or [])),
            "sponsor": (sponsor.get("leadSponsor") or {}).get("name", ""),
            "last_update": (status.get("lastUpdatePostDateStruct") or {}).get("date", ""),
        })
    out = resolve_path(args.out, f"literature/注册试验_{datetime.now():%Y%m%d}.csv")
    write_csv(out, rows, ["NCT", "title", "status", "type", "phase", "start", "primary_completion",
                          "enrollment", "condition", "intervention", "sponsor", "last_update"])
    print(f"[完成] ClinicalTrials.gov 命中 {len(rows)} 条 → {out}")
    if rows:
        print(md_table(["NCT", "状态", "类型", "入组", "干预"],
                       [[r["NCT"], r["status"], r["type"], r["enrollment"], r["intervention"]]
                        for r in rows[:15]]))
    return 0


# ---------------------------------------------------------------- 引用格式
def vancouver(rec: dict) -> str:
    authors = rec.get("authors") or []
    if len(authors) > 6:
        astr = ", ".join(authors[:6]) + ", et al"
    else:
        astr = ", ".join(authors)
    title = (rec.get("title") or "").rstrip(".")
    journal = rec.get("journal_abbr") or rec.get("journal") or ""
    year = rec.get("year") or ""
    vol = rec.get("volume") or ""
    issue = rec.get("issue") or ""
    pages = (rec.get("pages") or "").replace("-", "-")
    cite = f"{astr}. {title}. {journal}. {year}"
    if vol:
        cite += f";{vol}"
    if issue:
        cite += f"({issue})"
    if pages:
        cite += f":{pages}"
    cite += "."
    if rec.get("doi"):
        cite += f" doi:{rec['doi']}"
    if rec.get("pmid"):
        cite += f" PMID: {rec['pmid']}"
    return cite


# ---------------------------------------------------------------- 子命令
def _ids_from(text: str) -> list[str]:
    ids = re.findall(r"\b\d{6,9}\b", text)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def cmd_search(args) -> int:
    mindate = maxdate = None
    if args.years:
        m = re.match(r"(\d{4})\s*[-–]\s*(\d{4})", args.years)
        if not m:
            print("--years 格式应为 2018-2026", file=sys.stderr)
            return 2
        mindate, maxdate = m.group(1), m.group(2)
    count, ids = esearch(args.query, retmax=args.retmax, mindate=mindate or args.mindate,
                         maxdate=maxdate or args.maxdate, sort=args.sort)
    print(f"[检索] 命中 {count} 条，取前 {len(ids)} 条：{args.query}")
    if not ids:
        return 0
    arts = fetch_articles(ids)
    if args.out is None:
        out = resolve_path(None, f"literature/检索结果_{datetime.now():%Y%m%d_%H%M}.csv")
    else:
        out = resolve_path(args.out)
    fields = ["pmid", "doi", "year", "journal", "first_author", "title", "pubtype", "abstract"]
    write_csv(out, arts, fields)
    json_path = out.with_suffix(".json")
    write_json(json_path, {"query": args.query, "count": count, "retrieved": len(arts),
                           "date": datetime.now().isoformat(timespec="seconds"),
                           "articles": arts})
    print(f"[完成] {len(arts)} 条题录 → {out}\n        原始 JSON → {json_path}")
    print(md_table(["PMID", "年", "期刊", "标题"],
                   [[a["pmid"], a["year"], (a["journal_abbr"] or a["journal"])[:28],
                     a["title"][:70]] for a in arts[:12]]))
    if count > len(ids):
        print(f"（仅保存前 {len(ids)} 条；需要更多请加大 --retmax 或收窄检索式）")
    return 0


def cmd_fetch(args) -> int:
    ids = _ids_from(args.pmids or "")
    if args.id_file:
        ids += [i for i in _ids_from(resolve_path(args.id_file).read_text(encoding="utf-8"))
                if i not in ids]
    if not ids:
        print("需要 --pmids 或 --id-file", file=sys.stderr)
        return 2
    arts = fetch_articles(ids)
    fmt = args.format
    if fmt == "json":
        out = resolve_path(args.out, f"literature/题录_{datetime.now():%Y%m%d}.json")
        write_json(out, arts)
    elif fmt == "md":
        out = resolve_path(args.out, f"literature/题录_{datetime.now():%Y%m%d}.md")
        lines = [f"# 题录汇总（{len(arts)} 篇，{datetime.now():%Y-%m-%d}）", ""]
        for a in arts:
            lines += [f"## PMID {a['pmid']} · {a['year']}", "",
                      f"- **标题**：{a['title']}", f"- **期刊**：{a['journal']}",
                      f"- **作者**：{', '.join(a['authors'][:8])}",
                      f"- **DOI**：{a['doi'] or '未报告'}",
                      f"- **类型**：{a['pubtype'] or '未报告'}",
                      f"- **PubMed**：{a['pubmed_url']}", "",
                      f"**摘要**：{a['abstract'] or '（未报告）'}", ""]
        out.write_text("\n".join(lines), encoding="utf-8")
    else:
        out = resolve_path(args.out, f"literature/题录_{datetime.now():%Y%m%d}.csv")
        write_csv(out, arts, ["pmid", "doi", "year", "journal", "first_author", "title",
                              "pubtype", "abstract"])
    print(f"[完成] {len(arts)} 篇 → {out}")
    return 0


# 中文期刊常见 DOI 前缀（中华医学会 10.3760、维普/万方/知网代理等）。这些 DOI 多由中文 DOI
# 注册机构登记，Crossref/PubMed 查不到是常态，不代表 DOI 无效。
CN_DOI_PREFIXES = ("10.3760/", "10.3969/", "10.12116/", "10.11817/", "10.7507/", "10.16016/",
                   "10.13350/", "10.19538/", "10.12025/", "10.3877/", "10.3870/", "10.13481/",
                   "10.12300/", "10.16150/", "10.13406/", "10.3881/", "10.12659/")
CN_DOI_NOTE = ("未收录≠无效，需人工核：中文期刊 DOI 常未被 Crossref/PubMed 收录，"
               "请在 doi.org 解析或到中华医学期刊网/知网/万方按题名核对")


def _is_cn_doi(doi: str) -> bool:
    d = doi.lower()
    return d.startswith(CN_DOI_PREFIXES) or ".cma." in d or "cma.j" in d


def cmd_verify(args) -> int:
    if args.file:
        text = resolve_path(args.file).read_text(encoding="utf-8")
    else:
        text = args.text or ""
    pmids = list(dict.fromkeys(PMID_RE.findall(text)))
    dois = list(dict.fromkeys(DOI_RE.findall(text)))
    # 去掉 DOI 末尾误捕获的标点
    dois = [d.rstrip(".,;)]}") for d in dois]
    rows, missing = [], []
    if pmids:
        summary = esummary(pmids)
        for p in pmids:
            item = summary.get(p) or {}
            ok = bool(item) and item.get("error") != "cannot get document summary"
            rows.append({"类型": "PMID", "编号": p, "存在": "是" if ok else "否",
                         "标题": item.get("title", ""), "期刊/年": f"{item.get('source', '')} {item.get('pubdate', '')}".strip(),
                         "备注": ""})
            if not ok:
                missing.append(("PMID", p))
        time.sleep(SLEEP)
    for d in dois:
        found = ""
        title = ""
        try:
            data = __import__("json").loads(http_get(
                "https://api.crossref.org/works/" + d, headers={"User-Agent": "dshm-research-tool/1.0"}))
            msg = data.get("message", {})
            title = (msg.get("title") or [""])[0]
            found = msg.get("DOI", d)
        except Exception:
            try:
                _, ids = esearch(f'"{d}"[AID]', retmax=1)
                if ids:
                    item = esummary(ids).get(ids[0], {})
                    found, title = ids[0], item.get("title", "")
            except Exception:
                pass
        cn = _is_cn_doi(d)
        note = f"PubMed/DOI 匹配: {found}" if found else (CN_DOI_NOTE if cn else "")
        rows.append({"类型": "DOI", "编号": d, "存在": "是" if found else ("未收录" if cn else "否"),
                     "标题": title, "期刊/年": "", "备注": note})
        if not found:
            missing.append(("DOI(中文期刊)" if cn else "DOI", d))
        time.sleep(SLEEP)
    out = resolve_path(args.out, f"literature/文献核对_{datetime.now():%Y%m%d_%H%M}.csv")
    write_csv(out, rows, ["类型", "编号", "存在", "标题", "期刊/年", "备注"])
    print(f"[核对] PMID {len(pmids)} 个，DOI {len(dois)} 个 → {out}")
    if missing:
        print(f"[需人工核实] {len(missing)} 条未在 PubMed/Crossref 找到：")
        for kind, val in missing:
            print(f"  - {kind}: {val}")
        if any(k.startswith("DOI(中文") for k, _ in missing):
            print(f"[说明] {CN_DOI_NOTE}")
    else:
        print("[通过] 全部编号都能在 PubMed/Crossref 找到。")
    return 0 if not missing else 1


def cmd_cite(args) -> int:
    ids = _ids_from(args.pmids or "")
    if args.id_file:
        ids += [i for i in _ids_from(resolve_path(args.id_file).read_text(encoding="utf-8"))
                if i not in ids]
    if not ids:
        print("需要 --pmids 或 --id-file", file=sys.stderr)
        return 2
    arts = fetch_articles(ids)
    lines = [f"# 参考文献（Vancouver 格式，{datetime.now():%Y-%m-%d}）", ""]
    for n, a in enumerate(arts, 1):
        lines.append(f"{n}. {vancouver(a)}")
    text = "\n".join(lines) + "\n"
    if args.out:
        out = resolve_path(args.out)
        out.write_text(text, encoding="utf-8")
        print(f"[完成] {len(arts)} 条 → {out}")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PubMed/Europe PMC/ClinicalTrials.gov 科研检索工具",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="PubMed 检索并保存题录")
    s.add_argument("--query", required=True, help="PubMed 检索式（支持 [tiab]/[pt] 等字段标签）")
    s.add_argument("--retmax", type=int, default=50)
    s.add_argument("--years", help="年份范围，如 2018-2026（按发表日期）")
    s.add_argument("--mindate")
    s.add_argument("--maxdate")
    s.add_argument("--sort", default="relevance", choices=["relevance", "pub_date"])
    s.add_argument("--out", help="CSV 输出路径（默认 literature/检索结果_时间.csv）")
    s.set_defaults(func=cmd_search)

    f = sub.add_parser("fetch", help="按 PMID 抓完整题录与摘要")
    f.add_argument("--pmids", help="逗号分隔的 PMID")
    f.add_argument("--id-file", help="包含 PMID 的文件（自动提取数字）")
    f.add_argument("--format", default="csv", choices=["csv", "json", "md"])
    f.add_argument("--out")
    f.set_defaults(func=cmd_fetch)

    o = sub.add_parser("oa", help="抓取 Europe PMC 开放全文（txt）")
    o.add_argument("--pmid", required=True)
    o.add_argument("--outdir", default="fulltext")
    o.set_defaults(func=cmd_oa)

    c = sub.add_parser("ctgov", help="检索 ClinicalTrials.gov 注册试验")
    c.add_argument("--query", required=True)
    c.add_argument("--retmax", type=int, default=50)
    c.add_argument("--out")
    c.set_defaults(func=cmd_ctgov)

    v = sub.add_parser("verify", help="核对文档中的 PMID/DOI 是否真实存在")
    v.add_argument("--file", help="要扫描的 Markdown/XML 文本文件")
    v.add_argument("--text", help="直接给一段文本")
    v.add_argument("--out")
    v.set_defaults(func=cmd_verify)

    t = sub.add_parser("cite", help="按 PMID 生成 Vancouver 参考文献")
    t.add_argument("--pmids")
    t.add_argument("--id-file")
    t.add_argument("--out")
    t.set_defaults(func=cmd_cite)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
