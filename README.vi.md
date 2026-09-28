# Movie discovery agent

[English](README.md) | **Tiếng Việt**

Trợ lý hội thoại giúp một người dùng MovieLens tìm phim bằng cách thay họ tra cứu bộ dữ liệu: điểm họ đã chấm, điểm của những người dùng có gu tương tự, cốt truyện và thể loại. Trợ lý tự quyết định cần tra cứu gì, gọi các tool tất định (deterministic), và giải thích mọi gợi ý bằng bằng chứng lấy từ dữ liệu, không bao giờ từ kiến thức về phim sẵn có của LLM.

- **Báo cáo:** [`REPORT.vi.md`](REPORT.vi.md), bản tiếng Anh [`REPORT.md`](REPORT.md) (phân tích bài toán, cách tiếp cận, đánh giá, phân tích lỗi, nhìn lại)
- **Thiết kế:** [`docs/design.md`](docs/design.md) · **Sổ ghi chép:** [`docs/notes.md`](docs/notes.md) (tiếng Anh)
- **Đề bài và dữ liệu:** [`Exam/`](Exam/) (nguyên bản được giao, chỉ đọc)

## Demo

Một phiên `movie-agent chat --user 15` bằng tiếng Việt (3 phút 45 giây): năm trong sáu câu hỏi mẫu của đề bài, sau đó là các câu hỏi tiếp về phim mới hơn, phim hài, và phim The Matrix, vốn không có trong bộ dữ liệu (agent trả lời đúng như vậy). Sau mỗi câu trả lời, CLI in ra các tool đã gọi và kết quả verifier.

https://github.com/user-attachments/assets/a3c7d0c5-dd9f-4cc7-a897-6d72f838e863

## Cách hoạt động

```
User ──► Agent loop (OpenAI function calling + conversation state)
            │ tool calls                        ▲ verifier → renderer
            ▼                                   │
         5 tools: get_user_profile · find_movie · recommend · peer_opinion · explain
            ▼
         Ranking: filters → features (cf, content, query, seed, quality) → weighted blend
            ▼
         Engines: EASE · UserKNN · plot embeddings (bge-small, chunked, cached)
            ▼
         Data: validation · catalog + title resolution · statistics · temporal splits
```

- Python tính mọi con số, mọi thứ hạng và danh sách. LLM (gpt-4.1-mini) chỉ chọn tool và diễn đạt kết quả của tool thành câu trả lời.
- LLM chỉ nhắc tới phim qua placeholder `[[m:<movieId>]]`. Bộ render đổi placeholder thành "Tên phim (Năm)" lấy từ catalog, nên LLM không thể bịa ra tên phim.
- Một verifier tất định kiểm tra mỗi câu trả lời trước khi hiển thị: phim phải đến từ kết quả của tool, gợi ý phải tuân theo các ràng buộc, và con số phải khớp với output của tool. Câu trả lời không đạt được viết lại một lần; nếu vẫn không đạt, hệ thống dùng câu trả lời mẫu dựng từ output của tool.
- Mỗi lượt hội thoại được ghi vào một trace JSONL. `why-not` giải thích vì sao một phim bất kỳ không được gợi ý.

## Cài đặt

Cần Python 3.11.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # rồi điền OPENAI_API_KEY (chỉ cần cho agent, xem bên dưới)
```

Lệnh đầu tiên có xếp hạng phim sẽ tải model embedding chạy local `BAAI/bge-small-en-v1.5` (khoảng 130 MB, từ Hugging Face), rồi embed 16,204 đoạn cốt truyện, mất khoảng 1–2 phút trên CPU laptop. Vector được cache trong `cache/`, các lần chạy sau khởi động trong vài giây.

## Lệnh

| Lệnh | Tác dụng | Cần API key |
|---|---|---|
| `movie-agent validate` | Kiểm tra dữ liệu và ghi `eval/results/data_report.json` | không |
| `movie-agent chat --user 15` | Phiên hội thoại tương tác (nhập dòng trống để thoát); ghi `traces/<session>.jsonl` | có |
| `movie-agent why-not --user 15 --movie "Heat" --exclude-genres Animation` | Vì sao một phim không được gợi ý với các tham số này | không |
| `movie-agent eval offline --split val` | Metric xếp hạng so với baseline, kèm khoảng tin cậy bootstrap, và các lượt dò tham số trên val | không |
| `movie-agent eval search` | Top 5 cho mỗi truy vấn đã chấm; tính điểm từ sheet đã chấm `eval/search_judgments.csv` | không |
| `movie-agent eval agent` | 24 kịch bản trong `eval/scenarios.yaml`; lưu transcript và sheet rubric | có |
| `movie-agent eval honesty` | Độ trung thực của lời giải thích (không cần key), cùng test nhiễu dữ liệu và test attribution (cần key) | có |
| `movie-agent report-tables` | Sinh lại `eval/results/report_tables.md`, các hình, và các bảng trong `REPORT.md` và `REPORT.vi.md` | không |
| `movie-agent eval offline --split test --final` | Lần chạy duy nhất trên tập test; đã chạy và ghi trong `eval/results/test_runs.log` | không |

Kiểm tra: `pytest -q` (bộ dữ liệu tổng hợp nhỏ, LLM được mock, không cần mạng) và `ruff check . && ruff format --check .`.

## API bên ngoài

Chỉ agent dùng API bên ngoài: OpenAI chat completions với `gpt-4.1-mini` (đổi được trong `configs/default.yaml`), cho `chat`, `eval agent` và một phần `eval honesty`. Dữ liệu gửi đi gồm hội thoại và output của tool, vốn chỉ chứa giá trị từ bộ dữ liệu. Mỗi lượt dùng khoảng 7k token; một lần chạy đủ các kịch bản (29 lượt) tốn khoảng 200k token. Mọi thứ khác, kể cả embedding, chạy local.

Câu trả lời thay đổi đôi chút giữa các lần chạy dù temperature bằng 0, nên chạy lại `eval agent` cho số gần giống nhưng không trùng khít với số đã lưu (`REPORT.md` so sánh nhiều lần chạy).

## Ví dụ output (không cần API key)

- `transcripts/chat_user_{1,15,30}.md`: mỗi người dùng test một phiên `chat`, gồm đủ sáu câu hỏi mẫu trong đề bài. Trace đầy đủ tương ứng (mọi lần gọi tool kèm output, kết quả verifier, state) nằm trong `traces/examples/`.
- `eval/results/<date>_agent_*/transcripts/`: mọi kịch bản của mỗi lần đánh giá agent.
- `eval/results/`: mọi lần chạy đánh giá (metric, tóm tắt, bản chụp config, git commit); `eval/results/report_tables.md` và `eval/results/figures/` được sinh từ đây.
- `eval/grading/`: các gói chấm điểm và các sheet đã chấm, mỗi điểm kèm lý do.

## Tái lập kết quả

```bash
movie-agent validate
movie-agent eval offline --split val    # xếp hạng, dò tham số
movie-agent eval search                 # dùng eval/search_judgments.csv đã chấm
movie-agent eval agent                  # cần OPENAI_API_KEY
movie-agent eval honesty                # cần OPENAI_API_KEY cho phần dùng LLM
movie-agent report-tables
```

Mỗi lần chạy ghi vào một thư mục mới `eval/results/<date>_<name>/`, không ghi đè gì. Tập test chỉ được đánh giá một lần, từ commit gắn tag `final-eval`. Chạy lại sẽ thêm một dòng vào `eval/results/test_runs.log`, và báo cáo sẽ phải khai báo lần chạy đó.

## Cấu trúc repo

```
Exam/                     đề bài, mẫu báo cáo và dữ liệu (chỉ đọc)
configs/default.yaml      mọi tham số có thể chỉnh (file config duy nhất)
src/movie_agent/          data.py, catalog.py, engines.py, ranking.py, tools.py, llm.py,
                          agent.py, verifier.py, trace.py, diagnostics.py, cli.py,
                          prompts/system_v{1,2}.md, evaluation/
eval/                     truy vấn search và điểm chấm, kịch bản, rubric, grading/, results/
tests/                    bộ test pytest và bộ dữ liệu nhỏ
transcripts/  traces/examples/   hội thoại mẫu đã chọn lọc và trace của chúng
docs/                     design.md, notes.md
REPORT.md  REPORT.vi.md   báo cáo (tiếng Anh) và bản dịch tiếng Việt
```
