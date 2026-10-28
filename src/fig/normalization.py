"""Conservative HTML-to-passage normalizer; stores offsets into its own version."""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
from uuid import uuid5, NAMESPACE_URL
from fig.contracts import Passage, TextVersion

PARSER_VERSION="html-blocks-v1"
BLOCKS={"p","div","h1","h2","h3","h4","h5","h6","tr","li","section","article"}
VOID={"br","img","hr","input","meta","link","area","base","col","embed","param","source","track","wbr"}
SKIP={"script","style","noscript","ix:hidden","ix:header","head"}

class FilingHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.blocks=[]
        self.hidden=0
        self.heading=False

    def flush(self):
        text=re.sub(r"\s+"," ","".join(self.parts)).strip()
        if text:
            is_heading=self.heading or bool(re.match(r"^Item\s+[0-9]+[A-C]?\s*[.:]",text,re.I) and len(text)<180)
            self.blocks.append((is_heading,text))
        self.parts=[]
        self.heading=False

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.hidden:
            if tag not in VOID:
                self.hidden+=1
            return
        style=re.sub(r"\s+","",attrs.get("style","")).lower()
        if tag in SKIP or "display:none" in style or "visibility:hidden" in style or "hidden" in attrs:
            if tag not in VOID:
                self.hidden=1
            return
        if tag in BLOCKS:
            self.flush()
            self.heading=tag in {"h1","h2","h3","h4","h5","h6"}
        elif tag=="br":
            self.flush()
        elif tag in {"td","th"}:
            self.parts.append(" | ")

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self,tag):
        if self.hidden:
            self.hidden-=1
            return
        if tag in BLOCKS:
            self.flush()

    def handle_data(self,data):
        if not self.hidden:
            self.parts.append(data)

@dataclass(frozen=True)
class Normalized:
    text_version: TextVersion
    passages: list[Passage]
    quality_flags: list[str]


def normalize_html(original: bytes,document_id):
    if original.lstrip().startswith(b"%PDF"):
        raise ValueError("PDF normalization is not supported")
    flags=["section_labels_are_heuristic","tables_are_text_rows","toc_may_be_included"]
    try:
        html=original.decode("utf-8-sig")
    except UnicodeDecodeError:
        html=original.decode("cp1252",errors="strict")
        flags.append("decoded_windows_1252")
    if re.search(r"<(html|body|div|p|table)(?:\s|>)",html,re.I):
        parser=FilingHTMLParser();parser.feed(html);parser.close();parser.flush();source_blocks=parser.blocks
    else:
        try:root=ET.fromstring(html)
        except ET.ParseError as error:raise ValueError("Expected an HTML or XML filing") from error
        source_blocks=[]
        for element in root.iter():
            text=" ".join("".join(element.itertext()).split()) if len(element)==0 else ""
            if text:source_blocks.append((False,f"{element.tag.rsplit('}',1)[-1]}: {text}"))
        flags=["xml_leaf_elements","section_labels_are_element_names","tables_are_text_rows"]
    if not source_blocks:raise ValueError("Filing has no visible text")
    # Oversized visible blocks are split at word boundaries without altering
    # their text. Every passage refers to this exact normalized artifact.
    blocks=[]
    for heading,text in source_blocks:
        while len(text)>6000:
            split=text.rfind(" ",0,6000)
            if split<1:
                split=6000
            blocks.append((heading,text[:split]))
            text=text[split:].lstrip()
            heading=False
        if text:
            blocks.append((heading,text))
    text="\n\n".join(t for _,t in blocks)
    digest=sha256(text.encode()).hexdigest()
    version_id=uuid5(NAMESPACE_URL,f"fig:text:{document_id}:{PARSER_VERSION}:{digest}")
    version=TextVersion(id=version_id,document_id=document_id,parser_version=PARSER_VERSION,normalized_hash=digest,normalized_text=text)
    section="Unclassified"
    offset=0
    passages=[]
    for heading,block in blocks:
        if heading:
            section=block
        end=offset+len(block)
        passages.append(Passage(id=uuid5(NAMESPACE_URL,f"fig:passage:{version_id}:{offset}:{end}"),text_version_id=version_id,section_path=section,start_offset=offset,end_offset=end))
        offset=end+2
    return Normalized(version,passages,flags)
