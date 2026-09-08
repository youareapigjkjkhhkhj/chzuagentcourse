from agents.analyst_agent import analyze
from agents.planner_agent import plan_task
from agents.rag_agent import build_rag_context
from agents.reader_agent import reader_agent
from agents.search_agent import search_agent
from agents.writer_agent import write_report
from utils.file_utils import save_pdf, save_report


def main():
    topic = input("Enter research topic: ")

    print("Planning...")
    tasks = plan_task(topic)

    print("Searching papers...")
    papers = search_agent(tasks, topic=topic)

    print("Reading papers...")
    contents = reader_agent(papers, max_length=5000)

    print("Building RAG context...")
    rag_context, _ = build_rag_context(topic, contents)

    print("Analyzing...")
    summary = analyze(contents, topic=topic, rag_context=rag_context)

    print("Writing report...")
    report = write_report(summary, topic, papers, rag_context=rag_context)

    md_path = save_report(report, topic)
    pdf_path = save_pdf(report, topic)

    print(f"\nMarkdown saved to: {md_path}")
    print(f"PDF saved to: {pdf_path}")
    print("\n===== Final Report =====")
    print(report)


if __name__ == "__main__":
    main()
