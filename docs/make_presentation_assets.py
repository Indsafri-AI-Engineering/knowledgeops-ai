from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OUT = Path(__file__).parent
ARCH = OUT / "knowledgeops_architecture.png"
SWIM = OUT / "knowledgeops_whole_application_swimlane.png"
DOCX = OUT / "KnowledgeOps_Architecture_Code_Breakdown_and_Swimlane.docx"
PPTX = OUT / "KnowledgeOps_Architecture_Code_Breakdown_and_Swimlane.pptx"
NAVY = "#1B405D"; TEAL = "#11A88F"; BLUE = "#347FE8"; PURPLE = "#7252A5"
RED = "#B95C6B"; GREEN = "#2AA889"; CYAN = "#279DB5"; DARK = "#173E5B"

def architecture_image():
    fig, ax = plt.subplots(figsize=(13.5, 7.1), dpi=180)
    fig.patch.set_facecolor("white"); ax.set_facecolor("#F8FBFD")
    ax.set_xlim(0, 13.5); ax.set_ylim(0, 7.1); ax.axis("off")
    def box(x,y,w,h,title,body,color="#FFFFFF",edge=NAVY):
        p=FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.04,rounding_size=0.13",facecolor=color,edgecolor=edge,linewidth=1.6)
        ax.add_patch(p); ax.text(x+.16,y+h-.25,title,fontsize=11.2,fontweight="bold",color=NAVY,va="top")
        ax.text(x+.16,y+h-.58,body,fontsize=8.3,color="#31465B",va="top",linespacing=1.4)
    def arrow(a,b,label="",color="#58738C",rad=0):
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle="-|>",mutation_scale=12,linewidth=1.4,color=color,connectionstyle=f"arc3,rad={rad}"))
        if label: ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+.12,label,fontsize=7.1,color="#425C73",ha="center",bbox=dict(facecolor="#F8FBFD",edgecolor="none",pad=1))
    box(.3,4.85,2.15,1.25,"User / browser","Ask • upload • review\nReact + TypeScript")
    box(3.05,4.85,2.35,1.25,"Frontend app","ChatPanel • feature panels\nOIDC token • API client")
    box(3.05,2.8,2.35,1.25,"Keycloak / OIDC","Login • signed identity\nclaims", "#EAF7F5", TEAL)
    box(6.0,4.85,2.35,1.25,"FastAPI backend","API routes • auth • permissions\nmoderation • audit")
    box(6.0,2.8,2.35,1.4,"Knowledge pipeline","Route • scope-filtered retrieval\nEvidence • grounded answer")
    box(9.15,4.85,2.25,1.25,"MongoDB Atlas","Documents + chunks\nScoped vector search", "#EAF7F5", TEAL)
    box(9.15,2.8,2.25,1.25,"AI provider","Ollama / Groq / Mistral\nEmbeddings / generation", "#EAF7F5", TEAL)
    box(9.15,.75,2.25,1.25,"Jira Cloud","Separate authorized\nJira workspace", "#EAF7F5", TEAL)
    box(6.0,.75,2.35,1.25,"Threat & alerts","Local scanner • alerts\nOptional n8n", "#EAF7F5", TEAL)
    arrow((2.45,5.45),(3.0,5.45)); arrow((5.4,5.45),(5.95,5.45))
    arrow((4.22,4.8),(4.22,4.12)); arrow((5.4,3.42),(5.85,5.05),rad=-.2)
    arrow((7.17,4.8),(7.17,4.26)); arrow((8.4,3.65),(9.1,5.05),rad=-.12)
    arrow((8.4,3.25),(9.1,3.42))
    arrow((7.17,4.8),(7.17,2.05))
    ax.text(.3,6.55,"KNOWLEDGEOPS AI | APPLICATION ARCHITECTURE",fontsize=15,fontweight="bold",color=TEAL)
    ax.text(.3,.12,"Jira and threat-response operations are separate authorized feature routes; chat does not execute them.",fontsize=8,color="#52677C")
    fig.savefig(ARCH,bbox_inches="tight",facecolor="white"); plt.close(fig)

def swimlane_image():
    fig, ax=plt.subplots(figsize=(15,7.4),dpi=200)
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")
    labels=["USER","REACT FRONTEND","OIDC / IDENTITY","FASTAPI API","ORCHESTRATION","SECURITY","INTEGRATION / AUDIT"]
    ymap={lab:5.2-i*.82 for i,lab in enumerate(labels)}
    ax.set_xlim(-.2,14.7); ax.set_ylim(-.95,6.85); ax.set_yticks([]); ax.set_xticks([])
    for y in ymap.values(): ax.axhline(y,color="#D8E1EA",lw=.8,zorder=0)
    ax.spines[:].set_visible(False)
    for lab,y in ymap.items(): ax.text(-.12,y+.15,lab,ha="left",va="center",fontsize=7.5,fontweight="bold",color="#25374A")
    # Layout follows the supplied reference: lane and numbered hand-off order.
    steps=[(1,"Open application","USER",.55),(2,"Sign in / OIDC","OIDC / IDENTITY",1.65),(3,"Select feature\nsend request","REACT FRONTEND",2.65),(4,"Validate route\nand identity","FASTAPI API",3.65),(5,"Check capability","SECURITY",4.65),(6,"Derive scopes","SECURITY",5.65),(7,"Route intent","ORCHESTRATION",6.65),(8,"Retrieve evidence","ORCHESTRATION",7.65),(9,"Generate answer","ORCHESTRATION",8.65),(10,"Apply guardrails","SECURITY",9.65),(11,"Run feature","FASTAPI API",10.65),(12,"Build response\nand citations","FASTAPI API",11.65),(13,"Render result","REACT FRONTEND",12.65),(14,"Record audit","INTEGRATION / AUDIT",13.65)]
    colors={"USER":"#F39B45","REACT FRONTEND":"#347FE8","OIDC / IDENTITY":"#7252A5","FASTAPI API":"#2AA889","ORCHESTRATION":"#279DB5","SECURITY":"#B95C6B","INTEGRATION / AUDIT":"#173E5B"}
    points=[]
    for n,label,lane,x in steps:
        y=ymap[lane]-.21; c=colors[lane]
        patch=FancyBboxPatch((x,y),.86,.48,boxstyle="round,pad=0.025,rounding_size=.08",facecolor=c,edgecolor=c,lw=.8,zorder=3)
        ax.add_patch(patch); ax.text(x+.43,y+.34,str(n),ha="center",va="center",fontsize=8.2,fontweight="bold",color="white",zorder=4)
        ax.text(x+.43,y+.13,label,ha="center",va="center",fontsize=5.2,color="white",linespacing=1.0,zorder=4)
        points.append((x+.43,ymap[lane]))
    for i in range(len(points)-1):
        a,b=points[i],points[i+1]
        # Curved connectors keep the sequential handoffs legible between lane rows.
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle="-|>",mutation_scale=8,linewidth=.85,color="#8292A4",connectionstyle="arc3,rad=0.08",zorder=2,shrinkA=17,shrinkB=17))
    ax.text(0,6.58,"KnowledgeOps AI — Whole Application Swimlane",fontsize=15,fontweight="bold",color=NAVY)
    ax.text(0,6.28,"End-to-end flow: user entry, identity, API routing, authorization, orchestration, feature execution, response and audit.",fontsize=8.4,color="#50677E")
    ax.text(0,5.98,"SCOPE  Authentication  ·  Knowledge chat  ·  Knowledge management  ·  Jira  ·  Threat analysis  ·  Security alerts  ·  System status  ·  Audit",fontsize=7.4,color=NAVY,bbox=dict(boxstyle="square,pad=.35",facecolor="#EAF1F7",edgecolor="#CAD8E5"))
    ax.text(0,-.63,"HOW TO READ IT  Follow numbered nodes left to right. Arrows show hand-offs between lanes; security checks apply before protected retrieval or feature actions.",fontsize=7.6,color="#50677E")
    ax.text(0,-.9,"1–4 ENTRY & IDENTITY                         5–6 ACCESS CONTROL                         7–10 PROCESS & VALIDATE                         11–14 EXECUTE, RESPOND & AUDIT",fontsize=7.3,fontweight="bold",color="#246DB7")
    fig.savefig(SWIM,bbox_inches="tight",facecolor="white"); plt.close(fig)

def para(text, style=None):
    ppr=f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
def pagebreak(): return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
def word_picture(rel_id, name, cx=8500000, cy=4700000):
    pic_id=int(rel_id[3:])
    return f'''<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{pic_id}" name="{name}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic><pic:nvPicPr><pic:cNvPr id="{pic_id}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''

def make_docx():
    body=[]
    body += [para("KNOWLEDGEOPS AI", "Subtitle"), para("Project Architecture, Code Breakdown & Swimlane", "Title"), para("A presentation guide to the complete application, its key files, connected services, and end-to-end workflow.")]
    body += [para("PAGE 1 | WHOLE-PROJECT ARCHITECTURE", "Heading1"), word_picture("rId1","KnowledgeOps architecture",8500000,4450000), para("Main path: User → React frontend → FastAPI → verified identity and scope checks → retrieval and grounded generation → cited response and audit. Keycloak, MongoDB Atlas, and the configured model provider are external services. Jira and threat analysis are separate authorized feature routes.")]
    body += [pagebreak(), para("PAGE 2 | FRONTEND, IDENTITY & API ENTRY", "Heading1")]
    for h,t in [("Frontend — the user-facing lane","App.tsx initializes the OIDC callback and loads the current user. ChatPanel.tsx captures a question and renders the result and citations. api/chat.ts sends POST /api/v1/chat; api/http.ts attaches the current bearer token."),("Identity — who is making the request?","api/oidc.ts configures oidc-client-ts for authorization-code flow with PKCE. Keycloak authenticates the person and issues a signed token. core/auth.py verifies signature, issuer, audience, expiry, and claims; core/permissions.py maps trusted groups into capabilities and data scopes."),("API — the controlled entry point","main.py configures FastAPI, CORS, request IDs, and routes. api/v1/router.py mounts feature APIs. api/v1/chat.py validates the request, requires chat:ask, runs moderation and orchestration, audits the result, and returns ChatResponse.")]: body += [para(h,"Heading2"),para(t)]
    body += [para("How the files connect","Heading2"),para("App.tsx → oidc.ts → http.ts → chat.ts → main.py → router.py → chat.py → auth.py / permissions.py. A verified user context is established before protected work begins.")]
    body += [pagebreak(),para("PAGE 3 | CHAT ORCHESTRATION, RETRIEVAL & LLM", "Heading1")]
    for h,t in [("routing.py — classify intent","route_question() calls _classify_intent() to select a knowledge, analytical, workflow, or unsupported route, including required scope or clarification."),("orchestration/service.py — connect the route to work","orchestrate_request() checks required scope, chooses a feature path, and sends knowledge questions to the index. Unavailable actions receive a planned response; chat does not execute Jira writes or threat-response actions."),("knowledge/index.py and retrieval.py — find permitted evidence","get_knowledge_index() loads fictional seed files and stored chunks, then selects Atlas, Qdrant, or local retrieval. Search filters candidates by the user's allowed scopes. Hybrid mode combines vector and keyword rankings."),("knowledge/mongodb_index.py — vector retrieval","MongoAtlasKnowledgeIndex creates a query embedding and runs Atlas Vector Search with server-side access-scope filtering, then combines ranked results with lexical search."),("knowledge/generation.py + ai_providers.py — draft from evidence","generate_grounded_answer() abstains when there are no matching sources. Otherwise it passes retrieved evidence to a configured LangChain model. create_embeddings() and create_chat_model() connect Ollama or configured Mistral/Groq services."),("moderation/guardrails.py — safety around model use","Input, retrieved text, and answer output are inspected. Evidence is treated as untrusted reference content; the model is asked to answer only from supplied evidence.")]: body += [para(h,"Heading2"),para(t)]
    body += [para("Sequence","Heading2"),para("chat() → route_question() → orchestrate_request() → index.search(question, user_scopes) → inspect retrieved text → generate_grounded_answer() → output check → response with citations.")]
    body += [pagebreak(),para("PAGE 4 | INGESTION, STORAGE & OTHER FEATURES", "Heading1")]
    for h,t in [("Document upload and indexing","api/v1/knowledge_documents.py checks knowledge:manage, file type/size, duplicates, and ingestion configuration. PDF, Office, and text handlers extract sections. Security preflight and extracted-text inspection run before content is chunked and indexed. Original upload bytes are not retained."),("MongoDB Atlas persistence","storage/mongodb_knowledge.py stores document metadata and chunks separately, enforces unique content hashes, and creates supporting indexes. knowledge/mongodb_index.py indexes and retrieves scoped vectors."),("Jira Cloud — separate feature lane","api/v1/jira.py exposes dedicated endpoints; integrations/jira_cloud.py calls Jira REST using backend-only credentials. Reads require jira:read. Writes require jira:approve and explicit confirmation. Chat does not execute Jira operations."),("Threat scans, alerts, and n8n","api/v1/threat_scans.py exposes authorized scans. threat_detection/ applies local rules; scans do not execute files or fetch submitted URLs. Findings may create redacted alerts. Analyst-confirmed response requests and optional n8n notifications are separate from automatic remediation."),("Governance and audit","storage/audit.py records event metadata. Chat audit data includes route, outcome, and source count, not question/answer content. Request IDs and metrics are attached by main.py. Audit records and permissions support review and traceability.")]: body += [para(h,"Heading2"),para(t)]
    body += [para("External components at a glance","Heading2"),para("Keycloak: login and signed claims. MongoDB Atlas: document/chunk storage and vector search. Ollama, Groq, or Mistral: embeddings and/or answer generation according to configuration. Jira Cloud: separate ticket workflow. Optional n8n: event notification/confirmed workflow dispatch.")]
    body += [pagebreak(),para("PAGE 5 | WHOLE-APPLICATION SWIMLANE", "Heading1"),word_picture("rId2","Whole application swimlane",9000000,4500000),para("Follow the 14 numbered nodes from left to right. The lanes identify the responsible actor or component; arrows show hand-offs. Security checks apply before protected retrieval or feature actions. Feature-specific operations run only when implemented and authorized; Jira and threat workflows remain separate from chat.")]
    sect='<w:sectPr><w:pgSz w:w="15840" w:h="12240"/><w:pgMar w:top="650" w:right="750" w:bottom="650" w:left="750" w:header="300" w:footer="300" w:gutter="0"/></w:sectPr>'
    document='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>'+''.join(body)+sect+'</w:body></w:document>'
    styles='''<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/><w:sz w:val="20"/><w:color w:val="172033"/></w:rPr><w:pPr><w:spacing w:after="100" w:line="250"/></w:pPr></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="34"/><w:color w:val="1B405D"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="18"/><w:color w:val="11A88F"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="1B405D"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/><w:color w:val="16877F"/></w:rPr></w:style></w:styles>'''
    rels='''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/architecture.png"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/swimlane.png"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'''
    ct='''<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'''
    with ZipFile(DOCX,"w",ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",ct); z.writestr("_rels/.rels",'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",document); z.writestr("word/styles.xml",styles); z.writestr("word/_rels/document.xml.rels",rels); z.write(ARCH,"word/media/architecture.png"); z.write(SWIM,"word/media/swimlane.png")

SHAPE_ID=2
def tx(text,x,y,w,h,size=18,color="172033",bold=False,align="l"):
    global SHAPE_ID
    shape_id=SHAPE_ID; SHAPE_ID+=1
    paras=[]
    for line in text.split("\n"):
        paras.append(f'<a:p><a:pPr algn="{ {"l":"l","c":"ctr"}.get(align,"l") }"/><a:r><a:rPr lang="en-US" sz="{size*100}" b="{1 if bold else 0}"/><a:solidFill><a:srgbClr val="{color.lstrip("#")}"/></a:solidFill><a:t>{escape(line)}</a:t></a:r><a:endParaRPr lang="en-US" sz="{size*100}"/></a:p>')
    return f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Text {shape_id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{int(x*914400)}" y="{int(y*914400)}"/><a:ext cx="{int(w*914400)}" cy="{int(h*914400)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>{''.join(paras)}</p:txBody></p:sp>'
def pic(rel,x,y,w,h):
    global SHAPE_ID
    shape_id=SHAPE_ID; SHAPE_ID+=1
    return f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="Diagram {shape_id}"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="{rel}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill><p:spPr><a:xfrm><a:off x="{int(x*914400)}" y="{int(y*914400)}"/><a:ext cx="{int(w*914400)}" cy="{int(h*914400)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
def make_pptx():
    global SHAPE_ID
    slides=[]
    # 1: architecture overview
    shapes=tx("KNOWLEDGEOPS AI",.55,.3,6,.45,17,"11A88F",True)+tx("Whole-Project Architecture",.55,.78,8,.55,25,"1B405D",True)+pic("rId2",.35,1.45,12.55,5.45)
    slides.append((shapes,True))
    slides.append((tx("FRONTEND • IDENTITY • API",.6,.35,12,.45,14,"11A88F",True)+tx("How a request enters the system",.6,.85,12,.55,25,"1B405D",True)+tx("FRONTEND\nApp.tsx initializes OIDC and user state.\nChatPanel.tsx captures a question and displays result/citations.\napi/chat.ts posts to /api/v1/chat. api/http.ts attaches the bearer token.",.7,1.75,5.8,3.9,18,"172033")+tx("IDENTITY & API\noidc.ts uses authorization-code + PKCE with Keycloak.\ncore/auth.py verifies signed token claims.\ncore/permissions.py derives capabilities and scopes.\nmain.py mounts FastAPI and request IDs; router.py connects feature routes.\napi/v1/chat.py checks access, moderates, orchestrates, audits, responds.",6.85,1.75,5.7,4.5,17,"172033"),False))
    slides.append((tx("ORCHESTRATION • RETRIEVAL • LLM",.6,.35,12,.45,14,"11A88F",True)+tx("From question to evidence-backed answer",.6,.85,12,.55,25,"1B405D",True)+tx("1  routing.py classifies knowledge, analytical, workflow, or unsupported intent.\n\n2  orchestration/service.py checks scope and chooses the path.\n\n3  knowledge/index.py selects Atlas, Qdrant, or local retrieval.\n\n4  mongodb_index.py / retrieval.py retrieve only allowed-scope chunks and rank vector + keyword evidence.\n\n5  generation.py abstains without evidence or passes evidence to the configured LangChain model.\n\n6  guardrails.py checks input, retrieved text, and output before response.",.75,1.65,7.3,5.3,17,"172033")+tx("KEY RELATION\nchat() → route_question() → orchestrate_request() → index.search(user_scopes) → grounded generation → answer with citations.\n\nPROVIDERS\nOllama locally; Groq/Mistral only when configured. Embeddings support vector search; chat model drafts from retrieved context.",8.5,1.8,4.1,4.7,17,"1B405D",True),False))
    slides.append((tx("DOCUMENTS • STORAGE • CONNECTED FEATURES",.6,.35,12,.45,14,"11A88F",True)+tx("Other important lanes and their boundaries",.6,.85,12,.55,25,"1B405D",True)+tx("DOCUMENT INGESTION\nknowledge_documents.py validates permission, size/type, duplicates, and settings; format handlers extract text; security inspection precedes chunking and indexing. Original upload bytes are not retained.\n\nMONGODB ATLAS\nstorage/mongodb_knowledge.py stores document metadata and chunks separately. mongodb_index.py handles vector indexing and scoped search.\n\nJIRA CLOUD\nDedicated UI/API and jira_cloud.py integration. Reads require jira:read; writes require jira:approve plus confirmation. Backend-only credentials.\n\nTHREAT & ALERTS\nDedicated scan routes use local rules; findings can create redacted alerts. Optional n8n notifications/response dispatch are separate authorized actions.\n\nGOVERNANCE\nAudit records route, outcome, and source count; it omits chat text. Capabilities, scopes, source policy, and AI-provider settings govern access.",.75,1.55,12,5.6,15,"172033"),False))
    slides.append((tx("WHOLE-APPLICATION SWIMLANE",.55,.22,12,.48,18,"11A88F",True)+tx("End-to-end request flow • 14 numbered hand-offs",.55,.72,12,.42,20,"1B405D",True)+pic("rId2",.25,1.12,12.85,5.95),True))
    content_types=['<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>','<Default Extension="xml" ContentType="application/xml"/>','<Default Extension="png" ContentType="image/png"/>','<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>','<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>','<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>']
    for i in range(1,len(slides)+1): content_types.append(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
    ct='<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'+''.join(content_types)+'</Types>'
    with ZipFile(PPTX,"w",ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",ct)
        z.writestr("_rels/.rels",'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>')
        sids=''.join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1,len(slides)+1))
        z.writestr("ppt/presentation.xml",f'<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId9"/></p:sldMasterIdLst><p:sldIdLst>{sids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
        relpres=''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1,len(slides)+1))+'<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        z.writestr("ppt/_rels/presentation.xml.rels",f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relpres}</Relationships>')
        z.writestr("ppt/slideMasters/slideMaster1.xml",'<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="4472C4" accent2="ED7D31" accent3="A5A5A5" accent4="FFC000" accent5="5B9BD5" accent6="70AD47" hlink="0563C1" folHlink="954F72"/><p:sldLayoutIdLst><p:sldLayoutId id="1" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles/></p:sldMaster>')
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>')
        z.writestr("ppt/slideLayouts/slideLayout1.xml",'<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>')
        for i,(shapes,haspic) in enumerate(slides,1):
            SHAPE_ID=2
            if haspic:
                img_rel='architecture.png' if i==1 else 'swimlane.png'
                rel=f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/{img_rel}"/>'
                z.write(ARCH if i==1 else SWIM,f"ppt/media/{img_rel}")
            else: rel=''
            slide=f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{shapes}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
            z.writestr(f"ppt/slides/slide{i}.xml",slide)
            z.writestr(f"ppt/slides/_rels/slide{i}.xml.rels",f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>{rel}</Relationships>')
        z.writestr("docProps/app.xml",f'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>KnowledgeOps presentation generator</Application><Slides>{len(slides)}</Slides></Properties>')

if __name__=="__main__":
    architecture_image(); swimlane_image(); make_docx(); make_pptx()
    print(DOCX); print(PPTX)
