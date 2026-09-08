"""
文件处理器模块
支持多种文件格式的文本提取
"""
import os
import zipfile
import tempfile
from typing import List, Dict, Optional
from pathlib import Path
import logging

# 文件解析库
from pypdf import PdfReader
from docx import Document as DocxDocument
from openpyxl import load_workbook
from pptx import Presentation

logger = logging.getLogger(__name__)


class FileProcessor:
    """文件处理器 - 支持多种格式的文本提取"""
    
    SUPPORTED_FORMATS = ['txt', 'md', 'pdf', 'docx', 'xlsx', 'pptx']
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    
    def __init__(self):
        """初始化文件处理器"""
        self.temp_dir = tempfile.gettempdir()
    
    def validate_file(self, file_path: str, file_type: str) -> tuple[bool, Optional[str]]:
        """
        验证文件
        
        Args:
            file_path: 文件路径
            file_type: 文件类型
            
        Returns:
            (是否有效, 错误信息)
        """
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return False, "文件不存在"
        
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > self.MAX_FILE_SIZE:
            return False, f"文件大小超过限制 ({self.MAX_FILE_SIZE / 1024 / 1024}MB)"
        
        # 规范化文件类型
        file_type = file_type.lower().strip()
        
        # 处理特殊情况：如 .tar.gz 这样的双重扩展名
        if file_type == 'gz' and file_path.lower().endswith('.tar.gz'):
            file_type = 'tar.gz'
        
        # 检查文件格式
        if file_type not in self.SUPPORTED_FORMATS:
            return False, f"不支持的文件格式: {file_type}。支持的格式: {', '.join(self.SUPPORTED_FORMATS)}"
        
        return True, None
    
    def validate_zip_file(self, file_path: str) -> tuple[bool, Optional[str]]:
        """
        验证 ZIP/TAR.GZ 文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            (是否有效, 错误信息)
        """
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return False, "文件不存在"
        
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size > self.MAX_FILE_SIZE:
            return False, f"文件大小超过限制 ({self.MAX_FILE_SIZE / 1024 / 1024}MB)"
        
        # 检查文件类型
        is_zip = file_path.lower().endswith('.zip')
        is_tar_gz = file_path.lower().endswith('.tar.gz')
        
        if not is_zip and not is_tar_gz:
            return False, f"不支持的压缩格式。支持的格式: .zip, .tar.gz"
        
        # 验证文件有效性
        try:
            if is_zip:
                if not zipfile.is_zipfile(file_path):
                    return False, "无效的 ZIP 文件"
            else:  # is_tar_gz
                import tarfile
                if not tarfile.is_tarfile(file_path):
                    return False, "无效的 TAR.GZ 文件"
        except Exception as e:
            return False, f"文件验证失败: {str(e)}"
        
        return True, None
    
    def extract_text(self, file_path: str, file_type: str) -> str:
        """
        从文件提取文本内容
        
        Args:
            file_path: 文件路径
            file_type: 文件类型
            
        Returns:
            提取的文本内容
            
        Raises:
            ValueError: 文件验证失败
            Exception: 文件解析失败
        """
        # 验证文件
        is_valid, error_msg = self.validate_file(file_path, file_type)
        if not is_valid:
            raise ValueError(error_msg)
        
        # 根据文件类型调用相应的处理方法
        file_type = file_type.lower()
        
        try:
            if file_type == 'txt':
                return self.process_txt(file_path)
            elif file_type == 'md':
                return self.process_markdown(file_path)
            elif file_type == 'pdf':
                return self.process_pdf(file_path)
            elif file_type == 'docx':
                return self.process_docx(file_path)
            elif file_type == 'xlsx':
                return self.process_xlsx(file_path)
            elif file_type == 'pptx':
                return self.process_pptx(file_path)
            else:
                raise ValueError(f"不支持的文件格式: {file_type}")
        except Exception as e:
            logger.error(f"文件解析失败 [{file_type}]: {str(e)}")
            raise Exception(f"文件解析失败: {str(e)}")
    
    def process_txt(self, file_path: str) -> str:
        """
        处理 TXT 文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            文本内容
        """
        try:
            # 尝试多种编码
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.info(f"成功使用 {encoding} 编码读取 TXT 文件")
                    return content.strip()
                except UnicodeDecodeError:
                    continue
            
            # 如果所有编码都失败，使用二进制模式读取并忽略错误
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            logger.warning("使用 UTF-8 编码并忽略错误读取 TXT 文件")
            return content.strip()
            
        except Exception as e:
            raise Exception(f"TXT 文件读取失败: {str(e)}")
    
    def process_markdown(self, file_path: str) -> str:
        """
        处理 Markdown 文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            文本内容
        """
        # Markdown 文件本质上是文本文件，使用相同的处理方法
        return self.process_txt(file_path)
    
    def process_pdf(self, file_path: str) -> str:
        """
        处理 PDF 文件（使用 pypdf）
        
        Args:
            file_path: 文件路径
            
        Returns:
            提取的文本内容
        """
        try:
            reader = PdfReader(file_path)
            text_parts = []
            
            # 遍历所有页面
            for page_num, page in enumerate(reader.pages, 1):
                try:
                    text = page.extract_text()
                    if text.strip():
                        text_parts.append(f"--- 第 {page_num} 页 ---\n{text}")
                except Exception as e:
                    logger.warning(f"PDF 第 {page_num} 页提取失败: {str(e)}")
                    continue
            
            if not text_parts:
                raise Exception("PDF 文件中未提取到任何文本内容")
            
            return "\n\n".join(text_parts)
            
        except Exception as e:
            raise Exception(f"PDF 文件解析失败: {str(e)}")
    
    def process_docx(self, file_path: str) -> str:
        """
        处理 DOCX 文件（使用 python-docx）
        
        Args:
            file_path: 文件路径
            
        Returns:
            提取的文本内容
        """
        try:
            doc = DocxDocument(file_path)
            text_parts = []
            
            # 提取段落文本
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    text_parts.append(text)
            
            # 提取表格文本
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        if cell_text:
                            row_text.append(cell_text)
                    if row_text:
                        text_parts.append(" | ".join(row_text))
            
            if not text_parts:
                raise Exception("DOCX 文件中未提取到任何文本内容")
            
            return "\n\n".join(text_parts)
            
        except Exception as e:
            raise Exception(f"DOCX 文件解析失败: {str(e)}")
    
    def process_xlsx(self, file_path: str) -> str:
        """
        处理 XLSX 文件（使用 openpyxl）
        
        Args:
            file_path: 文件路径
            
        Returns:
            提取的文本内容
        """
        try:
            workbook = load_workbook(file_path, read_only=True, data_only=True)
            text_parts = []
            
            # 遍历所有工作表
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                text_parts.append(f"=== 工作表: {sheet_name} ===")
                
                # 遍历所有行
                for row in sheet.iter_rows(values_only=True):
                    # 过滤空值并转换为字符串
                    row_values = [str(cell) for cell in row if cell is not None and str(cell).strip()]
                    if row_values:
                        text_parts.append(" | ".join(row_values))
            
            workbook.close()
            
            if len(text_parts) <= 1:  # 只有标题，没有内容
                raise Exception("XLSX 文件中未提取到任何文本内容")
            
            return "\n".join(text_parts)
            
        except Exception as e:
            raise Exception(f"XLSX 文件解析失败: {str(e)}")
    
    def process_pptx(self, file_path: str) -> str:
        """
        处理 PPTX 文件（使用 python-pptx）
        
        Args:
            file_path: 文件路径
            
        Returns:
            提取的文本内容
        """
        try:
            prs = Presentation(file_path)
            text_parts = []
            
            # 遍历所有幻灯片
            for slide_num, slide in enumerate(prs.slides, 1):
                slide_text = []
                slide_text.append(f"--- 幻灯片 {slide_num} ---")
                
                # 提取幻灯片中的所有文本
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text.append(shape.text.strip())
                    
                    # 处理表格
                    if shape.has_table:
                        table = shape.table
                        for row in table.rows:
                            row_text = []
                            for cell in row.cells:
                                cell_text = cell.text.strip()
                                if cell_text:
                                    row_text.append(cell_text)
                            if row_text:
                                slide_text.append(" | ".join(row_text))
                
                if len(slide_text) > 1:  # 有内容（不只是标题）
                    text_parts.append("\n".join(slide_text))
            
            if not text_parts:
                raise Exception("PPTX 文件中未提取到任何文本内容")
            
            return "\n\n".join(text_parts)
            
        except Exception as e:
            raise Exception(f"PPTX 文件解析失败: {str(e)}")
    
    def process_zip(self, zip_path: str, kb_id: str) -> List[Dict]:
        """
        处理 ZIP/TAR.GZ 压缩包，批量提取文件
        
        Args:
            zip_path: ZIP/TAR.GZ 文件路径
            kb_id: 知识库 ID
            
        Returns:
            文件列表，每个元素包含:
            {
                'file_name': 文件名,
                'file_type': 文件类型,
                'content': 文本内容,
                'success': 是否成功,
                'error': 错误信息（如果失败）
            }
        """
        results = []
        temp_extract_dir = None
        
        try:
            # 检查文件类型
            is_tar_gz = zip_path.lower().endswith('.tar.gz')
            
            # 创建临时解压目录
            temp_extract_dir = tempfile.mkdtemp(prefix=f"kb_{kb_id}_")
            
            if is_tar_gz:
                # 处理 TAR.GZ 文件
                import tarfile
                if not tarfile.is_tarfile(zip_path):
                    raise ValueError("不是有效的 TAR.GZ 文件")
                
                with tarfile.open(zip_path, 'r:gz') as tar_ref:
                    # 获取文件列表
                    file_list = tar_ref.getnames()
                    logger.info(f"TAR.GZ 文件包含 {len(file_list)} 个文件")
                    
                    # 解压所有文件
                    tar_ref.extractall(temp_extract_dir)
            else:
                # 处理 ZIP 文件
                if not zipfile.is_zipfile(zip_path):
                    raise ValueError("不是有效的 ZIP 文件")
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    # 获取文件列表
                    file_list = zip_ref.namelist()
                    logger.info(f"ZIP 文件包含 {len(file_list)} 个文件")
                    
                    # 解压所有文件
                    zip_ref.extractall(temp_extract_dir)
            
            # 处理解压后的文件
            for root, dirs, files in os.walk(temp_extract_dir):
                for file_name in files:
                    # 跳过隐藏文件和系统文件
                    if file_name.startswith('.') or file_name.startswith('__'):
                        continue
                    
                    file_path = os.path.join(root, file_name)
                    file_ext = Path(file_name).suffix[1:].lower()  # 去掉点号
                    
                    # 检查是否是支持的格式
                    if file_ext not in self.SUPPORTED_FORMATS:
                        logger.warning(f"跳过不支持的文件格式: {file_name}")
                        results.append({
                            'file_name': file_name,
                            'file_type': file_ext,
                            'content': None,
                            'success': False,
                            'error': f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(self.SUPPORTED_FORMATS)}"
                        })
                        continue
                    
                    # 提取文本内容
                    try:
                        content = self.extract_text(file_path, file_ext)
                        results.append({
                            'file_name': file_name,
                            'file_type': file_ext,
                            'content': content,
                            'file_size': os.path.getsize(file_path),
                            'success': True,
                            'error': None
                        })
                        logger.info(f"成功处理文件: {file_name}")
                    except Exception as e:
                        logger.error(f"处理文件失败 {file_name}: {str(e)}")
                        results.append({
                            'file_name': file_name,
                            'file_type': file_ext,
                            'content': None,
                            'success': False,
                            'error': f"文件处理失败: {str(e)}"
                        })
            
            return results
            
        except Exception as e:
            logger.error(f"压缩文件处理失败: {str(e)}")
            raise Exception(f"压缩文件处理失败: {str(e)}")
        
        finally:
            # 清理临时文件
            if temp_extract_dir and os.path.exists(temp_extract_dir):
                try:
                    import shutil
                    shutil.rmtree(temp_extract_dir)
                    logger.info(f"清理临时目录: {temp_extract_dir}")
                except Exception as e:
                    logger.warning(f"清理临时目录失败: {str(e)}")
    
    def get_file_info(self, file_path: str) -> Dict:
        """
        获取文件信息
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件信息字典
        """
        if not os.path.exists(file_path):
            raise ValueError("文件不存在")
        
        file_name = os.path.basename(file_path)
        file_ext = Path(file_name).suffix[1:].lower()
        file_size = os.path.getsize(file_path)
        
        return {
            'file_name': file_name,
            'file_type': file_ext,
            'file_size': file_size,
            'is_supported': file_ext in self.SUPPORTED_FORMATS
        }
