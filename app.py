"""
Safetech SST – API de Geração de APR em PDF
Recebe JSON do Floot via webhook e retorna PDF gerado com ReportLab
"""

from flask import Flask, request, jsonify, send_file
import os, re, io
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
from urllib.request import urlopen
from reportlab.pdfgen.canvas import Canvas
def carregar_imagem_url(url):
    if not url:
        return None
    try:
        with urlopen(url, timeout=6) as resp:
            dados = resp.read()
        return ImageReader(io.BytesIO(dados))
    except Exception:
        return None

app = Flask(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────────
def build_styles(theme_hex="#093A8B"):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SubTituloBlue", fontSize=10, leading=13, spaceAfter=4,
        fontName="Helvetica-Bold", textColor=colors.HexColor(theme_hex)))
    styles.add(ParagraphStyle(name="CenterBlueBold", fontSize=10, leading=13,
        alignment=TA_CENTER, fontName="Helvetica-Bold", textColor=colors.HexColor(theme_hex)))
    styles.add(ParagraphStyle(name="NormalSmall", fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="Cell", fontSize=7.5, leading=9.5))
    styles.add(ParagraphStyle(name="CellBold", fontSize=7.5, leading=9.5, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="CellCenter", fontSize=7.5, leading=9.5, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="CellCenterBold", fontSize=7.5, leading=9.5,
        alignment=TA_CENTER, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="CellRed", fontSize=7.0, leading=9.0,
        alignment=TA_CENTER, fontName="Helvetica-Bold", textColor=colors.white))
    styles.add(ParagraphStyle(name="CellOrange", fontSize=7.0, leading=9.0,
        alignment=TA_CENTER, fontName="Helvetica-Bold", textColor=colors.HexColor("#7B3F00")))
    styles.add(ParagraphStyle(name="CenterSmall", fontSize=8.5, leading=11, alignment=TA_CENTER))
    styles.add(ParagraphStyle(name="LabelCellBlue", fontSize=8.5, leading=11,
        alignment=TA_RIGHT, fontName="Helvetica-Bold", textColor=colors.HexColor(theme_hex)))
    styles.add(ParagraphStyle(name="ValueCell", fontSize=8.5, leading=10, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="ValueCellTight", fontSize=8.5, leading=10, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="RecTitle", fontSize=8.5, leading=11,
        fontName="Helvetica-Bold", textColor=colors.HexColor(theme_hex)))
    styles.add(ParagraphStyle(name="RecItem", fontSize=8.0, leading=10.5))
    return styles

def P(txt, styles, bold=False, center=False):
    if center:
        return Paragraph(str(txt), styles["CellCenterBold" if bold else "CellCenter"])
    return Paragraph(str(txt), styles["CellBold" if bold else "Cell"])

def esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def classificar(score):
    if score <= 4:        return "Toleravel"
    if score in {6,8,9}:  return "Moderado"
    if score == 12:       return "Substancial"
    if score >= 16:       return "Intoleravel"
    return "Indefinido"

def aplicar_matriz(itens):
    out = []
    for it in itens:
        it2 = dict(it)
        it2["score"] = int(it2.get("prob", 1)) * int(it2.get("sev", 1))
        it2["classificacao"] = classificar(it2["score"])
        out.append(it2)
    return out

def tabela_legenda(styles):
    data = [[
        Paragraph("<=4", styles["CenterSmall"]), Paragraph("Toleravel", styles["CenterSmall"]),
        Paragraph("6-9", styles["CenterSmall"]),  Paragraph("Moderado", styles["CenterSmall"]),
        Paragraph("12", styles["CenterSmall"]),   Paragraph("Substancial", styles["CenterSmall"]),
        Paragraph("16", styles["CenterSmall"]),   Paragraph("Intoleravel", styles["CenterSmall"]),
    ]]
    tbl = Table(data,
        colWidths=[1.0*cm,2.8*cm,1.0*cm,2.8*cm,1.0*cm,3.0*cm,1.0*cm,3.0*cm],
        rowHeights=[0.55*cm], hAlign="CENTER")
    tbl.setStyle(TableStyle([
        ("GRID",(0,0),(-1,-1),0.75,colors.black),
        ("ALIGN",(0,0),(-1,-1),"CENTER"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("BACKGROUND",(1,0),(1,0),colors.HexColor("#A5D6A7")),
        ("BACKGROUND",(3,0),(3,0),colors.HexColor("#FFF176")),
        ("BACKGROUND",(5,0),(5,0),colors.HexColor("#FFB74D")),
        ("BACKGROUND",(7,0),(7,0),colors.HexColor("#EF5350")),
        ("TEXTCOLOR",(7,0),(7,0),colors.white),
        ("FONTSIZE",(0,0),(-1,-1),8.5),
    ]))
    return tbl

def split_elaborado(cab):
    nome = cab.get("elaborado_nome","")
    crea = cab.get("elaborado_crea","")
    if not nome:
        s = str(cab.get("elaborado_por",""))
        m = re.search(r'crea\s*/?\s*sp[:\s-]*([0-9\.\-\/]+)', s, re.I)
        if m:
            crea = m.group(1).strip()
            nome = re.split(r'crea\s*/?\s*sp[:\s-]*', s, flags=re.I)[0]
            nome = re.sub(r'[--]\s*$','',nome).strip()
        else:
            nome = s.strip()
    return nome, crea

def tabela_kv4(cab, styles, doc_width, label_w=4.5*cm):
    nome_elab = cab.get("responsavel_tecnico_nome") or split_elaborado(cab)[0]
    crea_elab = cab.get("responsavel_tecnico_doc_numero") or split_elaborado(cab)[1]
    crea_label = cab.get("responsavel_tecnico_doc_label") or "Crea/SP"
    kv = [
        ("Razao Social",    cab.get("empresa_razao","")),
        ("CNPJ (Empresa)",  cab.get("empresa_cnpj","")),
    ]
    cliente_razao = cab.get("cliente_razao","")
    cliente_cnpj  = cab.get("cliente_cnpj","")
    if cliente_razao or cliente_cnpj:
        kv.append(("Cliente", cliente_razao))
        kv.append(("CNPJ (Cliente)", cliente_cnpj))
    kv += [
        ("Funcao", cab.get("funcao","")),
        ("Jornada", cab.get("jornada","")),
        ("Inicio da Tarefa", cab.get("hora_inicio_tarefa","")),
        ("Previsao de Termino", cab.get("previsao_termino","")),
        ("Cidade/UF", f"{cab.get('cidade','')}/{cab.get('uf','')}"),
        ("Emissao", cab.get("emissao","")),
        ("Revisao", str(cab.get("revisao_num","0"))),
        ("Data de Revisao", cab.get("revisao_data","")),
        ("Elaborado por", nome_elab),
        (crea_label, crea_elab),
    ]
    pair_w = doc_width / 2.0
    val_w  = pair_w - label_w
    rows = []
    for i in range(0, len(kv), 2):
        k1,v1 = kv[i]
        k2,v2 = kv[i+1] if i+1 < len(kv) else ("","")
        rows.append([
            Paragraph(f"{esc(k1)}:", styles["LabelCellBlue"]),
            Paragraph(esc(v1), styles["ValueCell"]),
            Paragraph(f"{esc(k2)}:", styles["LabelCellBlue"]),
            Paragraph(esc(v2), styles["ValueCell"]),
        ])
    tbl = Table(rows, colWidths=[label_w,val_w,label_w,val_w], hAlign="CENTER")
    tbl.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("ALIGN",(0,0),(0,-1),"RIGHT"),
        ("ALIGN",(2,0),(2,-1),"RIGHT"),
        ("TOPPADDING",(0,0),(-1,-1),2),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
        ("LEFTPADDING",(0,0),(-1,-1),2),
        ("RIGHTPADDING",(0,0),(-1,-1),2),
    ]))
    return tbl

def sig_line(w, font="Helvetica", size=8.5):
    uw = max(1e-6, stringWidth("_", font, size))
    return "_" * max(8, int((w-2)/uw))

def tabela_colaboradores(styles, doc_width, colaboradores, label_w=2.0*cm,
                          ratios=(0.24,0.22,0.22,0.32)):
    par_w = [doc_width * r for r in ratios]
    val_w = [max(1.0*cm, pw - label_w) for pw in par_w]
    rows = []
    for col in colaboradores:
        rows.append([
            Paragraph("Colaborador:", styles["LabelCellBlue"]),
            Paragraph(esc(col.get("nome","")), styles["ValueCellTight"]),
            Paragraph("Funcao:", styles["LabelCellBlue"]),
            Paragraph(esc(col.get("funcao","")), styles["ValueCellTight"]),
            Paragraph("CPF:", styles["LabelCellBlue"]),
            Paragraph(sig_line(val_w[2]), styles["ValueCellTight"]),
            Paragraph("Assinatura:", styles["LabelCellBlue"]),
            Paragraph(sig_line(val_w[3]), styles["ValueCellTight"]),
        ])
    tbl = Table(rows, colWidths=[label_w,val_w[0],label_w,val_w[1],label_w,val_w[2],label_w,val_w[3]],
                hAlign="CENTER")
    tbl.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),1.5),
        ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
        ("LEFTPADDING",(0,0),(-1,-1),1),
        ("RIGHTPADDING",(0,0),(-1,-1),1),
    ]))
    return tbl

def tabela_responsavel(styles, doc_width, nome, doc_num, doc_label="CREA/SP",
                        label_w=2.4*cm, ratios=(0.44,0.22,0.34)):
    par_w = [doc_width * r for r in ratios]
    val_w = [max(1.0*cm, pw - label_w) for pw in par_w]
    row = [[
        Paragraph("Responsavel Tecnico:", styles["LabelCellBlue"]),
        Paragraph(esc(nome), styles["ValueCellTight"]),
        Paragraph(f"{esc(doc_label)}:", styles["LabelCellBlue"]),
        Paragraph(esc(doc_num), styles["ValueCellTight"]),
        Paragraph("Assinatura:", styles["LabelCellBlue"]),
        Paragraph(sig_line(val_w[2]), styles["ValueCellTight"]),
    ]]
    tbl = Table(row, colWidths=[label_w,val_w[0],label_w,val_w[1],label_w,val_w[2]],
                hAlign="CENTER")
    tbl.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),1.5),
        ("BOTTOMPADDING",(0,0),(-1,-1),1.5),
        ("LEFTPADDING",(0,0),(-1,-1),1),
        ("RIGHTPADDING",(0,0),(-1,-1),1),
    ]))
    return tbl
class RascunhoCanvas(Canvas):
    def __init__(self, *args, mostrar_marca_dagua=False, rastreio_conta="", **kwargs):
        super().__init__(*args, **kwargs)
        self._mostrar_marca_dagua = mostrar_marca_dagua
        self._rastreio_conta = rastreio_conta
    def showPage(self):
        if self._mostrar_marca_dagua:
            pw, ph = self._pagesize
            self.saveState()
            self.setFillColor(colors.Color(0.9, 0.1, 0.1, alpha=0.35))
            self.setFont("Helvetica-Bold", 72)
            self.translate(pw/2, ph/2)
            self.rotate(45)
            self.drawCentredString(0, 0, "RASCUNHO")
            self.drawCentredString(0, -80, "Safetech SST")
            if self._rastreio_conta:
                self.setFont("Helvetica", 18)
                self.drawCentredString(0, -130, self._rastreio_conta)
            self.restoreState()
        super().showPage()
def gerar_apr_pdf(cabecalho, itens, rascunho=False,
                  theme_hex="#093A8B",
                  rodape_plataforma="Safetech Brasil Ltda - CNPJ 62.462.256/0001-78 - Proprietaria do aplicativo Safetech SST | [www.safetech.com.br](https://www.safetech.com.br)",
                  rodape_profissional="",
                  titulo="APR - Analise Preliminar de Riscos",
                  rastreio_conta=""):

    styles  = build_styles(theme_hex)
    itens_p = aplicar_matriz(itens)
    emitido = datetime.now().strftime("%d/%m/%Y %H:%M")

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=4.2*cm,  bottomMargin=1.2*cm
    )
    img_cliente = carregar_imagem_url(cabecalho.get("logo_cliente_url"))
    img_elaboradora = carregar_imagem_url(cabecalho.get("logo_elaboradora_url"))

    def on_page(canvas, _doc):
        pw, ph = _doc.pagesize
        L, R = _doc.leftMargin, _doc.rightMargin
        canvas.saveState()
        canvas.setFillColor(colors.white)
        canvas.rect(0,0,pw,ph,stroke=0,fill=1)

           
        # Titulo
        canvas.setFont("Helvetica-Bold", 15)
        canvas.setFillColor(colors.HexColor(theme_hex))
        canvas.drawCentredString(pw/2.0, ph-1.7*cm, titulo)
        # Logos no cabecalho
        logo_h, logo_max_w = 2.2*cm, 4.5*cm
        if img_cliente:
            iw, ih = img_cliente.getSize()
            escala = min(logo_max_w/iw, logo_h/ih)
            w, h = iw*escala, ih*escala
            canvas.drawImage(img_cliente, L, ph-0.5*cm-h, width=w, height=h,
                              preserveAspectRatio=True, mask='auto')
        if img_elaboradora:
            iw, ih = img_elaboradora.getSize()
            escala = min(logo_max_w/iw, logo_h/ih)
            w, h = iw*escala, ih*escala
            canvas.drawImage(img_elaboradora, pw-R-w, ph-0.5*cm-h, width=w, height=h,
                              preserveAspectRatio=True, mask='auto')

        # Linha separadora
        canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
        canvas.setLineWidth(0.6)
        canvas.line(L, ph-2.1*cm, pw-R, ph-2.1*cm)

        # Rodape duplo
        y = _doc.bottomMargin - 0.3*cm
        canvas.setStrokeColor(colors.HexColor("#CCCCCC"))
        canvas.setLineWidth(0.5)
        canvas.line(L,y,pw-R,y)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        if rodape_profissional:
            canvas.drawString(L, y-0.45*cm, str(rodape_profissional))
        rt = f"Pag. {canvas.getPageNumber()} - Gerado em {emitido}"
        rw = canvas.stringWidth(rt,"Helvetica",7.5)
        canvas.drawString(pw-R-rw, y-0.45*cm, rt)
        canvas.setFont("Helvetica", 7.0)
        canvas.setFillColor(colors.HexColor("#999999"))
        pw2 = canvas.stringWidth(rodape_plataforma,"Helvetica",7.0)
        canvas.drawString(pw/2.0 - pw2/2.0, y-0.80*cm, rodape_plataforma)
        canvas.restoreState()

    elems = []
    elems.append(tabela_kv4(cabecalho, styles, doc.width))
    elems.append(Spacer(1,6))

    elems.append(Paragraph("Descricao de Atividades:", styles["SubTituloBlue"]))
    desc = re.sub(r"\s+"," ", str(cabecalho.get("descricao_atividades",""))).strip()
    elems.append(Paragraph(esc(desc), styles["NormalSmall"]))
    elems.append(Spacer(1,6))

    elems.append(Paragraph("GRAU DE RISCO = PROBABILIDADE x SEVERIDADE", styles["CenterBlueBold"]))
    elems.append(Spacer(1,3))
    elems.append(tabela_legenda(styles))
    elems.append(Spacer(1,6))

    col_w = [4.8*cm, 3.0*cm, 4.8*cm, 4.8*cm, 1.3*cm, 1.3*cm, 2.5*cm, 2.6*cm]

    header_row = [
        P("Processo / Atividade",       styles, bold=True),
        P("Perigo / Fator de Risco",    styles, bold=True),
        P("Dano",                       styles, bold=True),
        P("Medidas de Controle\nExistentes", styles, bold=True),
        P("Prob.", styles, bold=True, center=True),
        P("Sev.",  styles, bold=True, center=True),
        P("Grau de\nRisco",             styles, bold=True, center=True),
        P("Acoes /\nRecomendacoes",     styles, bold=True, center=True),
    ]
    data_tbl = [header_row]

    class_colors = {
        "Toleravel":   colors.HexColor("#A5D6A7"),
        "Moderado":    colors.HexColor("#FFF176"),
        "Substancial": colors.HexColor("#FFB74D"),
        "Intoleravel": colors.HexColor("#EF5350"),
    }

    rec_items = []
    rec_counter = 0

    for idx, it in enumerate(itens_p, 1):
        formula   = f"{it['prob']}x{it['sev']}={it['score']}"
        grau_cell = Paragraph(
            f"<b>{esc(it['classificacao'])}</b><br/>"
            f"<font size='6.5'>({formula})</font>",
            styles["CellCenter"]
        )

        grau = it["classificacao"]
        rec_text = it.get("recomendacoes","")
        if grau == "Toleravel":
            rec_cell = Paragraph("Manter as medidas de controle existentes.", styles["CellCenter"])
        elif grau == "Intoleravel":
            rec_cell = Paragraph("ATIVIDADE\nSUSPENSA", styles["CellRed"])
        else:
            rec_counter += 1
            rec_cell = Paragraph(f"Ver Rec. {rec_counter}", styles["CellOrange"])
            if rec_text:
                rec_items.append((rec_counter, it.get("atividade",""), rec_text))

        data_tbl.append([
            P(it.get("atividade",""),  styles),
            P(it.get("perigo",""),     styles),
            P(it.get("dano",""),       styles),
            P(it.get("medidas",""),    styles),
            Paragraph(str(it["prob"]), styles["CellCenter"]),
            Paragraph(str(it["sev"]),  styles["CellCenter"]),
            grau_cell,
            rec_cell,
        ])

    tbl = Table(data_tbl, colWidths=col_w, repeatRows=1)
    base_style = [
        ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#F3F4F6")),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("BOX",           (0,0),(-1,-1), 0.9, colors.HexColor("#8C8C8C")),
        ("INNERGRID",     (0,0),(-1,-1), 0.5, colors.HexColor("#B0B0B0")),
        ("LINEBELOW",     (0,0),(-1,0),  1.0, colors.HexColor("#6B7280")),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [colors.whitesmoke, colors.white]),
        ("ALIGN",         (4,1),(6,-1),  "CENTER"),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 3),
        ("RIGHTPADDING",  (0,0),(-1,-1), 3),
    ]
    for idx, it in enumerate(itens_p, 1):
        cor = class_colors.get(it["classificacao"])
        if cor:
            base_style.append(("BACKGROUND",(6,idx),(6,idx),cor))
        if it["classificacao"] == "Intoleravel":
            base_style.append(("TEXTCOLOR",  (6,idx),(6,idx), colors.white))
            base_style.append(("BACKGROUND", (7,idx),(7,idx), colors.HexColor("#EF5350")))
        elif it["classificacao"] in ("Moderado","Substancial"):
            base_style.append(("BACKGROUND", (7,idx),(7,idx), colors.HexColor("#FFF8E1")))
    tbl.setStyle(TableStyle(base_style))
    elems.append(tbl)

    if rec_items:
        elems.append(Spacer(1,10))
        elems.append(Paragraph("RECOMENDACOES E PRAZOS", styles["SubTituloBlue"]))
        for num, ativ, rec in rec_items:
            elems.append(Spacer(1,3))
            elems.append(Paragraph(f"Rec. {num} - {esc(ativ)}", styles["RecTitle"]))
            elems.append(Paragraph(esc(rec), styles["RecItem"]))

    elems.append(Spacer(1,8))
    pair_w = doc.width/2.0
    lw, vw = 3.5*cm, pair_w - 3.5*cm
    datas = Table([[
        Paragraph("Data Emissao:",    styles["LabelCellBlue"]),
        Paragraph(esc(cabecalho.get("emissao","")),      styles["ValueCell"]),
        Paragraph("Data de Revisao:", styles["LabelCellBlue"]),
        Paragraph(esc(cabecalho.get("revisao_data","")), styles["ValueCell"]),
    ]], colWidths=[lw,vw,lw,vw], hAlign="CENTER")
    datas.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("TOPPADDING",(0,0),(-1,-1),2),
        ("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    elems.append(datas)

    elems.append(Spacer(1,10))
    colabs = cabecalho.get("colaboradores") or []
    if colabs:
        elems.append(tabela_colaboradores(styles, doc.width, colabs))
    elems.append(Spacer(1,8))
    elems.append(tabela_responsavel(
        styles, doc.width,
        cabecalho.get("responsavel_tecnico_nome",""),
        cabecalho.get("responsavel_tecnico_doc_numero",""),
        cabecalho.get("responsavel_tecnico_doc_label","CREA/SP"),
    ))
    elems.append(Spacer(1,6))
    elems.append(Paragraph(
        f"Documento gerado automaticamente em {emitido}. "
        "A responsabilidade tecnica e legal e do profissional habilitado que assina este documento.",
        styles["NormalSmall"]
    ))

    doc.build(
        elems, onFirstPage=on_page, onLaterPages=on_page,
        canvasmaker=lambda *a, **kw: RascunhoCanvas(*a, mostrar_marca_dagua=rascunho, rastreio_conta=rastreio_conta, **kw),
    )
    buffer.seek(0)
    return buffer


# ── Endpoints da API ──────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Safetech SST – Gerador de APR", "version": "1.0"})

@app.route("/gerar-rascunho", methods=["POST"])
def gerar_rascunho():
    """Gera PDF com marca d'agua RASCUNHO – Safetech SST. Gratuito."""
    try:
        data = request.get_json()
        cabecalho = data.get("cabecalho", {})
        itens     = data.get("itens", [])
        rodape_prof = data.get("rodape_profissional", "")
        rastreio_conta = data.get("rastreio_conta", "")

        buffer = gerar_apr_pdf(
            cabecalho, itens,
            rascunho=True,
            rodape_profissional=rodape_prof,
            rastreio_conta=rastreio_conta
        )

        nome_arquivo = f"RASCUNHO_APR_{cabecalho.get('funcao','').replace(' ','_')}.pdf"
        return send_file(buffer, mimetype="application/pdf",
                        as_attachment=True, download_name=nome_arquivo)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route("/gerar-final", methods=["POST"])
def gerar_final():
    """Gera PDF final sem marca d'agua. Consome 1 credito."""
    try:
        data = request.get_json()
        cabecalho = data.get("cabecalho", {})
        itens     = data.get("itens", [])
        rodape_prof = data.get("rodape_profissional", "")

        buffer = gerar_apr_pdf(
            cabecalho, itens,
            rascunho=False,
            rodape_profissional=rodape_prof
        )

        nome_arquivo = f"APR_{cabecalho.get('funcao','').replace(' ','_')}_{cabecalho.get('empresa_razao','').replace(' ','_')[:20]}.pdf"
        return send_file(buffer, mimetype="application/pdf",
                        as_attachment=True, download_name=nome_arquivo)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
