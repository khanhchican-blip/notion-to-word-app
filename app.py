import streamlit as st
from notion_client import Client
import requests
import base64
import re
from weasyprint import HTML
import fitz  # PyMuPDF

NOTION_API_KEY = st.secrets["NOTION_API_KEY"]
notion = Client(auth=NOTION_API_KEY)

def extract_page_id(url):
    base_url = url.split('?')[0]
    last_segment = base_url.split('/')[-1]
    clean_segment = last_segment.replace("-", "")
    if len(clean_segment) >= 32:
        return clean_segment[-32:]
    return None

def get_page_title(page_id):
    try:
        page = notion.pages.retrieve(page_id=page_id)
        for prop in page['properties'].values():
            if prop['type'] == 'title' and prop['title']:
                raw_title = "".join([t['plain_text'] for t in prop['title']])
                clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title)
                return clean_title.strip()
    except Exception:
        pass
    return "Notion_Export"

def get_all_blocks(block_id):
    """Vòng lặp tải toàn bộ block (vượt qua giới hạn 100 blocks của Notion API)"""
    blocks = []
    cursor = None
    while True:
        response = notion.blocks.children.list(block_id=block_id, start_cursor=cursor)
        blocks.extend(response.get('results', []))
        cursor = response.get('next_cursor')
        if not cursor:
            break
    return blocks

def get_page_properties_html(page_id):
    """Trích xuất các thuộc tính (Môn học, Status) ở đầu trang"""
    page = notion.pages.retrieve(page_id=page_id)
    html = '<div class="properties-container">'
    
    # Lấy Tiêu đề chính
    title = "Untitled"
    for prop in page['properties'].values():
        if prop['type'] == 'title' and prop['title']:
            title = "".join([t['plain_text'] for t in prop['title']])
    html += f'<h1>{title}</h1>'
    html += '<table class="props-table">'
    
    # Lấy các Properties khác
    for prop_name, prop in page['properties'].items():
        if prop['type'] == 'title': continue
        
        val = ""
        if prop['type'] == 'rich_text':
            val = "".join([t['plain_text'] for t in prop['rich_text']])
        elif prop['type'] == 'select' and prop['select']:
            val = prop['select']['name']
        elif prop['type'] == 'multi_select':
            val = ", ".join([s['name'] for s in prop['multi_select']])
        elif prop['type'] == 'status' and prop['status']:
            val = prop['status']['name']
        elif prop['type'] == 'date' and prop['date']:
            val = prop['date']['start']
            
        if val:
            html += f'<tr><td class="prop-name">📍 {prop_name}</td><td class="prop-val">{val}</td></tr>'
            
    html += '</table></div><hr class="divider">'
    return html

def image_to_base64(url):
    try:
        response = requests.get(url)
        return base64.b64encode(response.content).decode('utf-8')
    except:
        return ""

def parse_blocks_to_html(blocks):
    html_content = ""
    for block in blocks:
        b_type = block['type']
        
        if b_type == 'paragraph':
            text = "".join([t['plain_text'] for t in block['paragraph']['rich_text']])
            html_content += f"<p>{text}</p>" if text.strip() else "<br>"
            
        elif b_type in ['heading_1', 'heading_2', 'heading_3']:
            level = b_type[-1]
            text = "".join([t['plain_text'] for t in block[b_type]['rich_text']])
            html_content += f"<h{level}>{text}</h{level}>"
            
        elif b_type == 'bulleted_list_item':
            text = "".join([t['plain_text'] for t in block['bulleted_list_item']['rich_text']])
            html_content += f"<ul><li>{text}</li></ul>"
            
        elif b_type == 'numbered_list_item':
            text = "".join([t['plain_text'] for t in block['numbered_list_item']['rich_text']])
            html_content += f"<ol><li>{text}</li></ol>"
            
        elif b_type == 'callout':
            text = "".join([t['plain_text'] for t in block['callout']['rich_text']])
            html_content += f'<div class="callout">{text}</div>'
            
        elif b_type == 'quote':
            text = "".join([t['plain_text'] for t in block['quote']['rich_text']])
            html_content += f'<blockquote>{text}</blockquote>'
            
        elif b_type == 'divider':
            html_content += '<hr class="divider">'
            
        elif b_type == 'equation':
            expr = block['equation']['expression']
            if "\\rule" not in expr and "\\color" not in expr:
                html_content += f"<p><i>{expr}</i></p>"
                
        elif b_type == 'image':
            image_type = block['image']['type']
            image_url = block['image'][image_type]['url']
            b64_img = image_to_base64(image_url)
            if b64_img:
                html_content += f'<img src="data:image/png;base64,{b64_img}" style="max-width:100%; border-radius:8px; margin: 10px 0;">'
                
        elif b_type == 'column_list':
            columns = get_all_blocks(block['id'])
            html_content += '<div class="column-list">'
            for i, col in enumerate(columns):
                col_class = "col-left" if i == 0 else "col-right"
                html_content += f'<div class="{col_class}">'
                col_blocks = get_all_blocks(col['id'])
                html_content += parse_blocks_to_html(col_blocks) 
                html_content += '</div>'
            html_content += '<div style="clear: both;"></div></div>'
            
    return html_content

def generate_pdf(html_body):
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet">
        <style>
            @page {{ size: A4; margin: 20mm 15mm; }}
            * {{ box-sizing: border-box; }}
            body {{
                font-family: 'Montserrat', sans-serif; font-size: 11pt; line-height: 1.6; color: #333; margin: 0; padding: 0;
            }}
            /* CSS Properties */
            h1 {{ font-size: 24pt; margin-bottom: 10px; }}
            .properties-container {{ margin-bottom: 20px; }}
            .props-table {{ width: 100%; border-collapse: collapse; font-size: 10pt; color: #555; }}
            .props-table td {{ padding: 6px 0; border-bottom: 1px solid #f1f1f1; }}
            .prop-name {{ width: 200px; font-weight: 600; color: #777; }}
            .divider {{ border: none; border-top: 1px solid #eee; margin: 20px 0; }}
            
            /* CSS Content Blocks */
            ul, ol {{ margin-top: 0; margin-bottom: 0; padding-left: 20px; }}
            li {{ margin-bottom: 5px; }}
            blockquote {{ border-left: 3px solid #333; margin: 10px 0; padding-left: 15px; font-style: italic; }}
            .callout {{ background-color: #f1f5f9; padding: 15px; border-radius: 6px; margin: 15px 0; font-weight: 500; }}
            
            /* CSS Chia Cột Float (Chống vỡ trang) */
            .column-list {{ width: 100%; }}
            .col-left {{ float: left; width: 30%; border-right: 2px solid #EBECED; padding-right: 15px; font-weight: 600; }}
            .col-right {{ float: left; width: 70%; padding-left: 15px; }}
        </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """
    pdf_bytes = HTML(string=full_html).write_pdf()
    return pdf_bytes

def show_pdf_preview(pdf_bytes):
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=150) 
            img_bytes = pix.tobytes("png")
            st.image(img_bytes, caption=f"Trang {page_num + 1}", use_container_width=True)
            st.markdown("---") 
    except Exception as e:
        st.error(f"Không thể tạo bản xem trước: {str(e)}")

# Giao diện Streamlit
st.set_page_config(page_title="Notion to PDF", layout="wide")
st.title("Chuyển đổi Notion sang PDF")

notion_url = st.text_input("Nhập link Notion của bạn vào đây:")

if notion_url:
    page_id = extract_page_id(notion_url)
    if not page_id:
        st.error("Link Notion không hợp lệ. Vui lòng kiểm tra lại.")
    else:
        if st.button("Bắt đầu xử lý"):
            with st.spinner("Đang trích xuất dữ liệu và dàn trang PDF..."):
                try:
                    page_title = get_page_title(page_id)
                    properties_html = get_page_properties_html(page_id)
                    blocks = get_all_blocks(page_id)
                    content_html = parse_blocks_to_html(blocks)
                    
                    # Ghép Properties và Content lại
                    full_html_body = properties_html + content_html
                    
                    pdf_bytes = generate_pdf(full_html_body)
                    st.success(f"Tạo file '{page_title}.pdf' thành công!")
                    
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        st.download_button(
                            label="Tải file PDF xuống",
                            data=pdf_bytes,
                            file_name=f"{page_title}.pdf",
                            mime="application/pdf"
                        )
                    with col2:
                        st.markdown("### Bản xem trước (Preview)")
                        show_pdf_preview(pdf_bytes)
                        
                except Exception as e:
                    st.error(f"Đã xảy ra lỗi: {str(e)}\n\nVui lòng đảm bảo bạn đã Share trang Notion với Integration.")
