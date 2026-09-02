import streamlit as st
from notion_client import Client
import requests
import io
import base64
import re
import pdfkit

# Lấy API Key từ Streamlit Secrets
NOTION_API_KEY = st.secrets["NOTION_API_KEY"]
notion = Client(auth=NOTION_API_KEY)

def extract_page_id(url):
    """Trích xuất ID an toàn, bỏ qua ngày tháng trùng lặp"""
    base_url = url.split('?')[0]
    last_segment = base_url.split('/')[-1]
    clean_segment = last_segment.replace("-", "")
    if len(clean_segment) >= 32:
        return clean_segment[-32:]
    return None

def get_page_title(page_id):
    """Lấy tiêu đề trang từ API và làm sạch để làm tên file"""
    try:
        page = notion.pages.retrieve(page_id=page_id)
        # Quét các thuộc tính của trang để tìm trường chứa tiêu đề (type = title)
        for prop in page['properties'].values():
            if prop['type'] == 'title':
                if prop['title']:
                    raw_title = "".join([t['plain_text'] for t in prop['title']])
                    # Lọc bỏ các ký tự cấm trong tên file của Windows/Mac
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title)
                    return clean_title.strip()
    except Exception:
        pass
    # Tên mặc định dự phòng nếu có lỗi xảy ra
    return "Notion_Export"

def image_to_base64(url):
    """Chuyển ảnh từ Notion thành Base64 để nhúng an toàn vào file PDF"""
    try:
        response = requests.get(url)
        return base64.b64encode(response.content).decode('utf-8')
    except:
        return ""

def parse_blocks_to_html(blocks):
    """Chuyển đổi các khối Notion thành mã HTML"""
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
            
        elif b_type == 'equation':
            expr = block['equation']['expression']
            # BỘ LỌC TỰ ĐỘNG: Bỏ qua mã LaTeX tạo đường kẻ ngang/dọc của template
            if "\\rule" not in expr and "\\color" not in expr:
                html_content += f"<p><i>{expr}</i></p>"
                
        elif b_type == 'image':
            image_type = block['image']['type']
            image_url = block['image'][image_type]['url']
            b64_img = image_to_base64(image_url)
            if b64_img:
                html_content += f'<img src="data:image/png;base64,{b64_img}" style="max-width:100%; border-radius:8px; margin: 10px 0;">'
                
        elif b_type == 'column_list':
            columns = notion.blocks.children.list(block_id=block['id']).get('results', [])
            html_content += '<table class="cornell-table"><tr>'
            for i, col in enumerate(columns):
                # Chia cột 30% (Keyword) và 70% (Note), tạo viền xám giả lập đường kẻ LaTeX
                col_class = "col-left" if i == 0 else "col-right"
                html_content += f'<td class="{col_class}">'
                col_blocks = notion.blocks.children.list(block_id=col['id']).get('results', [])
                html_content += parse_blocks_to_html(col_blocks) # Đệ quy để lấy nội dung trong cột
                html_content += '</td>'
            html_content += '</tr></table>'
            
    return html_content

def generate_pdf(html_body):
    """Ghép CSS (Font, Size, Layout) và xuất PDF"""
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Montserrat', sans-serif;
                font-size: 14pt;
                line-height: 1.6;
                color: #333;
            }}
            .cornell-table {{
                width: 100%;
                border-collapse: collapse;
                page-break-inside: auto;
                margin-bottom: 20px;
            }}
            tr {{ page-break-inside: avoid; page-break-after: auto; }}
            td {{ vertical-align: top; padding: 15px; }}
            .col-left {{ 
                width: 30%; 
                border-right: 2px solid #EBECED; 
                font-weight: 600;
            }}
            .col-right {{ width: 70%; }}
        </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """
    options = {
        'page-size': 'A4',
        'margin-top': '0.75in',
        'margin-right': '0.75in',
        'margin-bottom': '0.75in',
        'margin-left': '0.75in',
        'encoding': "UTF-8",
        'enable-local-file-access': None
    }
    pdf_bytes = pdfkit.from_string(full_html, False, options=options)
    return pdf_bytes

def show_pdf_preview(pdf_bytes):
    """Hiển thị bản xem trước PDF trực tiếp trên web"""
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

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
                    # Lấy tiêu đề trang
                    page_title = get_page_title(page_id)
                    
                    # Lấy dữ liệu nội dung
                    blocks = notion.blocks.children.list(block_id=page_id).get('results', [])
                    html_body = parse_blocks_to_html(blocks)
                    
                    # Tạo PDF
                    pdf_bytes = generate_pdf(html_body)
                    st.success(f"Tạo file '{page_title}.pdf' thành công!")
                    
                    # Chia giao diện làm 2 cột: Trái để nút tải, Phải để Preview
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
