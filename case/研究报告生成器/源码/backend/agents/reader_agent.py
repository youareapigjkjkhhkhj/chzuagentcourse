from tools.pdf_reader import read_pdf_from_url


def reader_agent(papers, max_length=3000):
    """
    安全读取论文列表中的 PDF 内容。

    参数：
        papers: list of dict，每个 dict 包含 title 和 pdf_url
        max_length: 每篇论文返回的最大字符长度，避免内存过大

    返回：
        list of dict，每个 dict 保留论文元数据并增加 text
    """
    contents = []

    for paper in papers:
        title = paper.get("title", "No Title")
        pdf_url = paper.get("pdf_url", "")

        if not pdf_url:
            print(f"[跳过] {title} 没有 PDF URL")
            continue

        text = read_pdf_from_url(pdf_url, max_length=max_length)
        if text:
            item = dict(paper)
            item["text"] = text
            contents.append(item)
        else:
            print(f"[跳过] {title} PDF 内容为空或下载失败")

    return contents
