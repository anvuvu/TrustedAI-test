# Báo cáo: Vũ Trường An

[English](REPORT.md) | **Tiếng Việt**

> Đây là bản dịch tiếng Việt của [`REPORT.md`](REPORT.md). Bản tiếng Anh là bản chính: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Các bảng số liệu do `movie-agent report-tables` sinh tự động cho cả hai bản nên giữ nguyên tiếng Anh. Số được viết theo quy ước tiếng Anh (dấu chấm thập phân, dấu phẩy phân cách hàng nghìn) để khớp với các bảng. Câu hỏi của người dùng và câu trích từ câu trả lời của hệ thống được giữ nguyên văn tiếng Anh, vì hệ thống chạy bằng tiếng Anh.

**Tóm tắt trong một đoạn.**
- **Kiến trúc.** Trợ lý trả lời dựa trên một tập con của MovieLens thông qua năm tool tất định. LLM (gpt-4.1-mini) chỉ chọn tool và diễn đạt kết quả của chúng. LLM nhắc tới phim qua placeholder chứa ID, và một verifier kiểm tra mọi câu trả lời trước khi người dùng nhìn thấy.
- **Độ chính xác.** Trên tập test giữ riêng, chỉ dùng một lần, bộ xếp hạng được triển khai hoà với EASE (NDCG@10 0.113) và vượt baseline MostPopular +0.029 [0.016, 0.041].
- **Trung thực.** Trong test nhiễu dữ liệu (perturbation), cả 6 câu trả lời (3 phim, mỗi phim trên điểm thật và điểm đã đảo) đều đi theo dữ liệu, kể cả với phim nổi tiếng.
- **Chỗ hệ thống thất bại.** Hệ thống thừa hưởng lỗi của dữ liệu: khoảng 6% cốt truyện thuộc về một phim khác. Gợi ý dựa trên một phim gốc tìm ra các phim cùng *chủ đề*, không phải cùng *phẩm chất*. LLM vẫn có xu hướng gõ tay tên phim và thêm tính từ lấy từ kiến thức riêng của nó. Mọi con số dưới đây đều đến từ một lần chạy được lưu trong `eval/results/`, và mọi bảng đều do `movie-agent report-tables` sinh ra.

**Điểm chấm được tạo ra thế nào.** Thiết kế đã đăng ký trước (pre-registered) rằng tôi sẽ tự chấm kết quả search và rubric câu trả lời. Vì lý do thời gian, việc chấm được giao cho một **grader LLM độc lập**: các subagent Claude mới, không tham gia xây dựng hệ thống. Các grader này chỉ nhận hướng dẫn chấm bằng văn bản và dữ liệu, và không biết biến thể nào tạo ra mỗi kết quả search. Mỗi điểm đều có lý do bằng văn bản trong `eval/grading/`. Sai lệch này được liệt kê cùng các sai lệch khác ở cuối báo cáo.

## Phân tích bài toán (Problem Analysis)

**Người dùng là ai và họ cần gì?** Người dùng là người có lịch sử chấm điểm trong bộ dữ liệu, được xác định bằng user ID. Lịch sử dài từ 10 đến 1,907 lượt chấm, trung vị 56. Họ đến với ba loại câu hỏi:
- "What should I watch tonight?" (mở, mang tính cá nhân);
- một yêu cầu có ràng buộc ("a dark psychological thriller", "like Toy Story but not animated");
- một câu hỏi về một phim cụ thể hoặc về chính họ ("what do people like me think of Pulp Fiction?", "what's my blind spot?").

Họ cần những gợi ý hợp với yêu cầu và gu của mình, kèm lý do có thể tự kiểm chứng. Họ cũng cần được báo khi dữ liệu quá mỏng để nói được nhiều.

Với một bài take-home, còn một nhóm người đọc thứ hai cũng quan trọng: người review. Họ cần kiểm chứng được rằng mọi khẳng định đều đến từ dữ liệu, nên hệ thống phải truy vết được.

**Thế nào là một gợi ý hội thoại tốt?**
- **Đúng yêu cầu:** trả lời đúng điều được hỏi, và ràng buộc được cộng dồn qua các lượt ("no animation" vẫn còn hiệu lực hai lượt sau).
- **Cá nhân hoá:** đến từ lịch sử của chính người dùng này, không phải từ độ phổ biến chung.
- **Giải thích bằng bằng chứng kiểm chứng được:** "you rated Alien 5.0 and users who rated Alien also rated this", chứ không phải "a gripping classic".
- **Nói đúng mức chắc chắn (calibrated):** "only 2 similar users rated it" tốt hơn một phỏng đoán tự tin.
- **Ngắn gọn:** 3–5 lựa chọn, kèm lời đề nghị đi sâu hơn.

**Các thách thức kỹ thuật chính**, đo trên dữ liệu (`movie-agent validate`, `eval/results/data_report.json`):
1. **Phim thưa dữ liệu.** 37% số phim có dưới 3 lượt chấm, và 51% có dưới 5. Lọc cộng tác (collaborative filtering) gần như chỉ nhìn thấy một phần ba catalog, và "chất lượng" chỉ là nhiễu với phần lớn các phim.
2. **Người dùng thưa dữ liệu.** 171 trên 610 người dùng có từ 30 lượt chấm trở xuống; người dùng 30 trong đề bài có 18. Một người dùng (53) chấm mọi phim 5.0, nên không có tín hiệu nào về sở thích của họ.
3. **Một LLM vốn đã biết các phim này.** gpt-4.1-mini có sẵn ý kiến về Pulp Fiction. Đề bài yêu cầu trả lời từ dữ liệu (yêu cầu R3), nên thiết kế phải khiến việc "trả lời theo trí nhớ" khó xảy ra và dễ bị phát hiện.
4. **Văn bản cốt truyện là tín hiệu yếu và không hoàn hảo.** Cốt truyện mô tả sự kiện, không mô tả không khí (tone) của phim. Như phần đánh giá phát hiện, khoảng 6% cốt truyện mô tả một phim khác.
5. **Đánh giá rất khó.** Điểm chấm bị thiếu không ngẫu nhiên (missing not at random). Các tập đã chấm nhỏ (10 truy vấn, 24 kịch bản). LLM không tất định kể cả ở temperature 0.

## Cách tiếp cận (Approach)

**Tôi chia nhỏ bài toán thế nào.** Tôi tách hệ thống thành các tầng, mỗi tầng một việc, và đánh giá từng tầng riêng để có thể quy một lỗi về đúng một tầng:

| Tầng | Việc | Được đánh giá bằng |
|---|---|---|
| Dữ liệu | kiểm tra dữ liệu, phân giải tên phim, thống kê, chia tập theo thời gian cho từng người dùng | `validate`; unit test phân giải tên phim |
| Engine và xếp hạng | EASE, UserKNN và embedding cốt truyện; chấm điểm toàn bộ catalog; đóng góp theo từng feature | xếp hạng offline so với baseline, kèm khoảng tin cậy bootstrap |
| Tool | 5 tool trả về dữ liệu kèm độ tin cậy và cảnh báo | unit test; `why-not` |
| Agent | vòng lặp LLM chọn tool, rồi verifier, rồi renderer, có state qua các lượt | 24 kịch bản, rubric câu trả lời, các test trung thực |

Các câu hỏi mẫu ứng với các chuỗi tool: "tonight" → `recommend`; "similar taste … Pulp Fiction" → `find_movie` → `peer_opinion`; "why would I like that" → `explain`; "Toy Story but not animated" → `find_movie` → `recommend(seed, exclude_genres)`; "blind spot" → `get_user_profile` → `recommend(include_genres)`.

**Phương pháp và lý do.**
- **EASE làm bộ gợi ý:** một model tuyến tính item-item có nghiệm dạng đóng (closed form). Nó tất định, thường mạnh trên MovieLens, và phần đóng góp đọc được: "điểm bạn chấm cho X cộng thêm chừng này vào Y".
- **UserKNN cho câu hỏi "những người giống bạn":** câu hỏi về người cùng gu cần những người láng giềng có thật, xem được, kèm số phim chung, chứ không phải các nhân tố ẩn (latent factors).
- **Embedding cốt truyện cho các mô tả:** `bge-small-en-v1.5` chạy local. Cốt truyện được cắt thành các đoạn khoảng 300 token, và một phim được chấm theo đoạn khớp nhất, nên cốt truyện dài không bị loãng và đoạn khớp có thể hiển thị làm bằng chứng.
- **Một hàm xếp hạng duy nhất:** toàn bộ catalog (5,135 phim) được chấm điểm cho mỗi yêu cầu, nên không có giai đoạn chọn ứng viên nào làm rơi mất phim. Mỗi feature được đổi thành điểm thứ hạng trong top 200 của riêng nó, rồi trộn với trọng số theo từng chế độ. Các phần đóng góp cộng lại đúng bằng điểm, và chúng chính là nguồn gốc (provenance) được đưa cho LLM và ghi vào trace.
- **Bám dữ liệu ngay từ cấu trúc (grounded by construction):**
  - LLM viết `[[m:ID]]`, không bao giờ viết tên phim.
  - Verifier kiểm tra ba điều: phim đến từ kết quả tool và không có tên phim nào bị gõ tay; gợi ý đến từ `recommend` và tuân theo ràng buộc; mọi con số đều xuất hiện trong output của tool.
  - Câu trả lời không đạt được viết lại một lần; nếu vẫn không đạt, hệ thống dựng câu trả lời mẫu từ dữ liệu của tool.
- **Truy vết được:** một trace JSONL cho mỗi lượt, và `why-not <movie>`, lệnh chạy lại bộ xếp hạng và cho biết một phim bị lọc, bị xếp thấp hơn, hay không hề có trong catalog.

**Các phương án đã cân nhắc và loại bỏ.**
- **Câu trả lời tự do dựa trên ngữ cảnh truy xuất (RAG):** tôi sẽ không thể bắt buộc được R3.
- **Framework kiểu LangChain:** che giấu state và làm việc kiểm tra khó hơn.
- **Phân rã ma trận (matrix factorization):** không có lợi rõ ràng so với EASE ở quy mô này, và lời giải thích khó đọc hơn.
- **Learning-to-rank:** quá ít nhãn.
- **BM25 và viết lại truy vấn:** thêm nhiều thứ phải tinh chỉnh; việc viết lại còn có thể lén đưa kiến thức bên ngoài vào.
- **Dùng tag làm nhãn đánh giá:** chỉ 45 người viết toàn bộ tag, và một người trong số đó viết 43%.
- **Embedding của OpenAI:** được cân nhắc giữa chừng vì tải model chậm, rồi vẫn giữ bản local (miễn phí, chạy offline, tái lập được).
- **Thiết kế đầu tiên với 9 tool, 8 luật:** cắt xuống bản gọn cho vừa ngân sách thời gian. Danh sách phần bị cắt nằm ở `docs/design.md` §1.3.

### Nhật ký quyết định (Decision Log)

| Quyết định | Phương án thay thế đã cân nhắc | Vì sao tôi chọn cách này |
|---|---|---|
| LLM không bao giờ tự viết tên phim hay con số: tool trả về dữ liệu, phim là placeholder `[[m:ID]]`, và một verifier tất định kiểm tra mỗi câu trả lời (một lần viết lại, rồi câu trả lời mẫu) | Câu trả lời tự do của LLM dựa trên dữ liệu truy xuất (RAG) | Cách này biến yêu cầu "trả lời từ dữ liệu, không từ kiến thức của LLM" thành thứ bắt buộc được và đo được. Trong đánh giá, verifier chặn mọi tên phim bị gõ tay (lỗi chính), và chặn một ID phim bịa (`[[m:1107]]`, một phim chưa tool nào trả về) trước khi tới người dùng. Trong test nhiễu dữ liệu, cả 6 câu trả lời đều theo dữ liệu, kể cả 3 câu trên điểm đã đảo |
| Trộn các feature dưới dạng **điểm thứ hạng trong top 200 của mỗi feature**, không có trọng số riêng cho người dùng thưa dữ liệu (sửa lại sau validation) | Thiết kế đầu: percentile rank trên toàn catalog, và thêm trọng số content cho người dùng thưa dữ liệu | Trên tập val, thiết kế đầu **thua chính thành phần của nó** là EASE (NDCG@10 0.050 so với 0.102). Percentile ép top 200 của EASE vào khoảng 0.96–1.00, nên chênh lệch nhỏ về content đảo lộn nhóm đầu, và việc dịch trọng số cho người dùng thưa làm hại chính họ (0.059 so với 0.076). Điểm thứ hạng top 200 hoà với EASE (val 0.099; test 0.113 so với 0.113) và giữ chế độ query bám vào truy vấn (88% top 5 nằm trong 50 phim khớp cốt truyện nhất, so với 46%) |
| Lưu thể loại bị loại trừ bằng code: bộ điều phối thêm các thể loại bị loại trong `recommend` vào state hội thoại (thêm sau khi chấm) | Để LLM cập nhật state qua `final_answer.add_exclude_genres`, như thiết kế ban đầu | Chỉ dựa vào prompt, "no animation" được giữ ở 4/6 lượt trong một lần chạy và 1/6 trong một lần chạy giống hệt. Trong một trace, lần gọi tiếp theo bỏ mất ràng buộc và kết quả có Toy Story 3. Sau thay đổi, tỷ lệ giữ là 6/6 trong hai lần chạy |

Toàn bộ nhật ký, gồm mười một quyết định và trạng thái của chúng sau validation, nằm trong `docs/design.md` §14.

## Đánh giá (Evaluation)

**Làm sao tôi biết hệ thống hoạt động?** Mỗi yêu cầu được đo ở nơi có thể tách riêng nó, luôn so với baseline và kèm độ bất định:

| Yêu cầu | Đo bằng | Vì sao chọn cách đo này |
|---|---|---|
| R1 cá nhân hoá | Xếp hạng offline trên tập chia theo thời gian cho từng người dùng. Mọi phim chưa xem đều được xếp hạng (không lấy mẫu âm), kèm khoảng tin cậy bootstrap 95% theo người dùng và so sánh theo cặp | Cho thấy model cá nhân hoá có vượt các baseline không cá nhân hoá không, và với ai. Tập test được dùng một lần (`eval/results/test_runs.log`, commit gắn tag `final-eval`) |
| Truy vấn theo nội dung | 10 truy vấn mô tả, top 5 được chấm 0/1/2 | Không có nhãn cho "dark thriller with a twist", nên phải chấm |
| R2 nhiều bước, ràng buộc | 24 kịch bản (6 câu hỏi mẫu × người dùng 1, 15, 30, cộng 6 trường hợp biên) với kiểm tra tự động và rubric 4 tiêu chí | Kiểm tra việc chọn tool, bám dữ liệu, xử lý ràng buộc và trung thực trong hội thoại thật |
| R3 dữ liệu, không phải kiến thức LLM | Test nhiễu dữ liệu và độ trung thực của lời giải thích | Đây là test trực tiếp duy nhất: nếu dữ liệu đổi, câu trả lời có đổi theo không? Lý do được nêu có thực sự quyết định thứ hạng không? |

Với xếp hạng, "liên quan" nghĩa là một điểm chấm được giữ lại có giá trị từ 4.0 trở lên. Định nghĩa tương đối theo người dùng (điểm ≥ trung bình của người dùng + 0.5) cũng được báo cáo trong kết quả. Nó cho cùng một bức tranh: ba hệ lọc cộng tác bỏ xa MostPopular, còn MostPopular đứng trên TopBayesian và content profile. Theo định nghĩa đó, UserKNN nhỉnh hơn EASE một chút.

### Xếp hạng offline (tập test, dùng một lần)

<!-- table:offline -->
*Source: Offline ranking (test, K = 10, 590 users) — `2026-09-27_offline_test`*

| System | Recall@K | NDCG@K | Tail recall | Coverage | Pop. ratio |
|---|---|---|---|---|---|
| MostPopular | 0.065 [0.054, 0.076] | 0.084 [0.071, 0.096] | 0.000 [0.000, 0.000] | 0.018 | 3.43 |
| TopBayesian | 0.051 [0.041, 0.062] | 0.065 [0.055, 0.076] | 0.000 [0.000, 0.000] | 0.010 | 2.29 |
| UserKNN | 0.083 [0.072, 0.095] | 0.107 [0.094, 0.120] | 0.000 [0.000, 0.000] | 0.033 | 2.64 |
| EASE | 0.098 [0.085, 0.111] | 0.113 [0.100, 0.126] | 0.000 [0.000, 0.000] | 0.085 | 2.13 |
| ContentProfile | 0.008 [0.004, 0.011] | 0.009 [0.006, 0.013] | 0.008 [0.002, 0.017] | 0.084 | 0.18 |
| Blend | 0.097 [0.085, 0.111] | 0.113 [0.101, 0.127] | 0.003 [0.000, 0.009] | 0.074 | 2.27 |

| Comparison | Metric | Mean difference [95% CI] | Significant |
|---|---|---|---|
| Blend - EASE | recall | -0.001 [-0.011, 0.007] | no |
| Blend - EASE | ndcg | 0.000 [-0.008, 0.009] | no |
| EASE - MostPopular | recall | 0.034 [0.021, 0.047] | yes |
| EASE - MostPopular | ndcg | 0.029 [0.016, 0.041] | yes |
<!-- /table:offline -->

![Recall và NDCG theo hệ thống](eval/results/figures/accuracy_by_system.png)

- **Cá nhân hoá có tác dụng, ở mức khiêm tốn.** EASE đạt NDCG@10 0.113, cao hơn có ý nghĩa so với MostPopular (0.084, chênh lệch theo cặp +0.029 [0.016, 0.041]); bản thân MostPopular là một baseline mạnh, như thường thấy trên MovieLens. Blend được triển khai hoà với EASE (chênh lệch 0.000 [−0.008, 0.009]): nó không thêm được gì đo được. Các feature content và quality của nó không làm giảm độ chính xác, và cung cấp bằng chứng cốt truyện dùng trong lời giải thích.
- **UserKNN bám sát** (0.107). Với người dùng có lịch sử dài, nó nhỉnh hơn một chút (0.148 so với 0.142 của EASE ở nhóm một phần ba cao nhất, khoảng tin cậy chồng nhau). UserKNN tồn tại để trả lời câu hỏi về người cùng gu, nên độ chính xác của nó là phần thưởng thêm.
- **Thiên lệch độ phổ biến.** Phim do EASE và Blend gợi ý phổ biến gấp 2.1–2.3 lần các phim trong lịch sử của chính người dùng. Tail recall gần như bằng 0 với mọi hệ lọc cộng tác (Blend đạt 0.003). Chỉ content profile tìm được phim ở đuôi dài (0.008), và nhìn chung nó kém (0.009).

<!-- table:segments -->
*Source: NDCG@10 by train-history tercile (cut points 28, 79 ratings) — `2026-09-27_offline_test`*

| System | small | medium | large |
|---|---|---|---|
| MostPopular | 0.078 [0.057, 0.103] | 0.068 [0.052, 0.086] | 0.106 [0.086, 0.127] |
| TopBayesian | 0.056 [0.038, 0.077] | 0.049 [0.035, 0.065] | 0.090 [0.072, 0.111] |
| UserKNN | 0.080 [0.062, 0.099] | 0.094 [0.073, 0.114] | 0.148 [0.123, 0.175] |
| EASE | 0.109 [0.084, 0.135] | 0.087 [0.068, 0.107] | 0.142 [0.118, 0.169] |
| ContentProfile | 0.013 [0.005, 0.023] | 0.003 [0.001, 0.006] | 0.011 [0.006, 0.016] |
| Blend | 0.107 [0.084, 0.130] | 0.092 [0.072, 0.114] | 0.140 [0.114, 0.165] |
<!-- /table:segments -->

- Với người dùng ít lịch sử (nhóm một phần ba thấp nhất, từ 28 lượt chấm train trở xuống), EASE và Blend vẫn vượt MostPopular (0.109 và 0.107 so với 0.078). Kỳ vọng đăng ký trước rằng content sẽ giúp người dùng thưa dữ liệu **không** được xác nhận: ở nhóm này Blend không tốt hơn EASE.
- Các kỳ vọng đăng ký trước, đã kiểm tra:
  - MostPopular mạnh: xác nhận (nó vượt TopBayesian).
  - EASE chính xác nhất: xác nhận, hoà với Blend.
  - Content quan trọng hơn cho đuôi dài và người dùng thưa dữ liệu: chỉ xác nhận với đuôi dài.

### Tìm kiếm theo nội dung (Content search)

<!-- table:search -->
*Source: Content search (10 queries) — `2026-09-27_search_2`*

| Variant | P@5 | Mean grade (0–2) | Mean Bayesian avg | Share < 5 ratings |
|---|---|---|---|---|
| plain | 0.84 [0.72, 0.94] | 1.32 [1.08, 1.52] | 3.65 | 0.26 |
| plain_min0 | 0.88 [0.78, 0.96] | 1.38 [1.18, 1.56] | 3.64 | 0.42 |
| personal_u15 | 0.74 [0.58, 0.88] | 1.14 [0.94, 1.36] | 3.71 | 0.16 |
<!-- /table:search -->

<!-- table:search_failures -->
*Source: Search grades by query (LLM-graded) — `eval/grading/search_grades_with_rationale.csv`*

| Query | Pairs | Mean grade | genre_only | other | partial_element | title_word | wrong_tone |
|---|---|---|---|---|---|---|---|
| q01_dark_twist | 8 | 1.38 | 0 | 0 | 2 | 1 | 1 |
| q02_unlikely_friends | 9 | 1.11 | 0 | 1 | 3 | 1 | 1 |
| q03_bleak_loneliness | 8 | 0.75 | 0 | 2 | 3 | 2 | 0 |
| q04_road_trip | 7 | 1.29 | 1 | 0 | 2 | 0 | 1 |
| q05_heist_crew | 6 | 1.50 | 0 | 0 | 3 | 0 | 0 |
| q06_time_travel | 8 | 1.12 | 1 | 2 | 1 | 0 | 0 |
| q07_wrongly_accused | 7 | 1.29 | 0 | 2 | 1 | 0 | 0 |
| q08_space_survival | 10 | 0.70 | 4 | 0 | 5 | 0 | 0 |
| q09_war_romance | 7 | 1.57 | 0 | 0 | 3 | 0 | 0 |
| q10_haunted_house | 9 | 1.33 | 2 | 0 | 2 | 0 | 0 |
| all | 79 | 1.18 | 8 | 7 | 25 | 4 | 3 |
<!-- /table:search_failures -->

- **Truy vấn cốt truyện cụ thể hoạt động tốt** (heist 1.50, war romance 1.57): Heat, Ocean's Eleven, Back to the Future, Poltergeist, Doctor Zhivago. **Truy vấn về không khí và truy vấn trừu tượng thì không.** "A bleak, atmospheric film about loneliness" được 0.75. "Survival in space after an accident" (0.70) trả về các phim space opera có tàu bị hỏng trong chiến đấu.
- Loại lỗi chiếm ưu thế là `partial_element` (25 trên 47 điểm dưới 2): một phần của yêu cầu khớp, phần khác thiếu. Khớp chữ trong tên phim, do tiền tố "Title. Genres." ở mỗi đoạn, chỉ giải thích 4 trường hợp.
- Bỏ bộ lọc mặc định `min_ratings = 3` không giúp được một cách có ý nghĩa (P@5 0.88 so với 0.84), và làm tỷ lệ kết quả gần như không có ai chấm tăng từ 26% lên 42%, nên bộ lọc được giữ.
- Cá nhân hoá kết quả search (người dùng 15) làm giảm độ liên quan một chút (0.74, không có ý nghĩa), vì feature CF kéo vào các phim yêu thích của người dùng nhưng ít khớp truy vấn hơn.

### Kịch bản agent (Agent scenarios)

<!-- table:agent -->
*Source: Agent scenarios (24 scenarios, 29 turns) — `2026-09-27_agent_4`*

| Metric | Value |
|---|---|
| scenario_success | 0.792 |
| tool_chain_accuracy | 1.000 |
| verifier_first_pass_rate | 0.793 |
| fallback_rate | 0.000 |
| constraint_satisfaction | 1.000 |
| state_persistence | 1.000 |
| mean_tool_calls | 1.414 |
| mean_tokens | 6576.172 |
| p50_latency_ms | 2871.500 |
| p95_latency_ms | 4723.580 |

| Rubric criterion (0–2) | Mean | Graded turns |
|---|---|---|
| grounded | 1.45 | 29 |
| relevant | 1.97 | 29 |
| specific | 1.72 | 29 |
| honest | 1.90 | 29 |
<!-- /table:agent -->

Mọi lần chạy kịch bản, theo thứ tự:
- lần chạy Step 1 (bộ xếp hạng bản nháp, prompt v1);
- prompt v1 trên bộ xếp hạng đã sửa;
- prompt v2, chạy hai lần (chỉ khác một bản sửa verifier, không ảnh hưởng các lượt này);
- sau hai bản sửa rút ra từ việc chấm điểm (D9, D10), chạy hai lần;
- gpt-5.1 thay cho gpt-4.1-mini, cùng prompt và code (xem mục đổi model bên dưới; điểm chấm mù theo cặp của nó nằm trong bảng ở mục đó).

`-dirty` đánh dấu các lần chạy trên thay đổi chưa commit, được commit ngay sau đó.

<!-- table:agent_runs -->
*Source: All agent runs*

Rubric columns are means (0–2) where the run was graded (by an LLM grader, see notes).

| Run | Model | Prompt | Commit | verifier_first_pass_rate | fallback_rate | state_persistence | scenario_success | rubric grounded | rubric relevant | rubric specific | rubric honest |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `2026-09-26_agent` | gpt-4.1-mini | system_v1 | 6ef7177-dirty | 0.52 | 0.03 | 0.00 | 0.46 | - | - | - | - |
| `2026-09-27_agent` | gpt-4.1-mini | system_v1 | c315916-dirty | 0.48 | 0.10 | 0.00 | 0.50 | - | - | - | - |
| `2026-09-27_agent_2` | gpt-4.1-mini | system_v2 | c315916-dirty | 0.79 | 0.00 | 0.67 | 0.67 | - | - | - | - |
| `2026-09-27_agent_3` | gpt-4.1-mini | system_v2 | c315916-dirty | 0.86 | 0.03 | 0.17 | 0.71 | 1.45 | 1.86 | 1.66 | 1.45 |
| `2026-09-27_agent_4` | gpt-4.1-mini | system_v2 | 03ffabb | 0.79 | 0.00 | 1.00 | 0.79 | 1.45 | 1.97 | 1.72 | 1.90 |
| `2026-09-27_agent_5` | gpt-4.1-mini | system_v2 | 03ffabb | 0.76 | 0.00 | 1.00 | 0.75 | - | - | - | - |
| `2026-09-27_agent_6` | gpt-5.1 | system_v2 | 7a2a4e6-dirty | 0.72 | 0.03 | 1.00 | 0.75 | - | - | - | - |
<!-- /table:agent_runs -->

- **Việc chọn tool đúng ở mọi lượt của mọi lần chạy gpt-4.1-mini** (tool-chain accuracy 1.00), kể cả các trường hợp biên:
  - The Matrix được báo là không có trong bộ dữ liệu.
  - "Psycho" nhận được một câu hỏi làm rõ, liệt kê bản phim 1960 và bản làm lại 1998.
  - Yêu cầu "Just use what you know" bị từ chối.
  - Với một phim ít người biết, không có điểm của người cùng gu, câu trả lời nói rõ điều đó.
- **Lỗi LLM chính là gõ tay tên phim.** Mọi lần verifier từ chối trong các lần chạy gpt-4.1-mini cuối cùng đều là tên phim bị gõ tay, và lần viết lại đều khắc phục được. Prompt v2 nâng tỷ lệ đạt ngay lần đầu từ 0.48 lên khoảng 0.8 và giảm tỷ lệ phải dùng câu trả lời mẫu từ 0.10 xuống 0.00–0.03.
- **Biến động giữa các lần chạy là có thật.** Hai lần chạy giống hệt với v2 cho tỷ lệ giữ state 0.67 và 0.17, đó là lý do bản sửa này được chuyển vào code (xem nhật ký quyết định). Sau thay đổi, tỷ lệ là 1.00 ở cả hai lần chạy.
- **Rubric (grader LLM)** sau hai bản sửa: relevant 1.97, specific 1.72, honest 1.90, **grounded 1.45**. Lần chạy trước các bản sửa được chấm bởi một grader khác, nên sự thay đổi chỉ mang tính tham khảo. Mức bám dữ liệu (grounded) là điểm yếu. Sáu điểm 0 của tiêu chí này đến từ hai nguyên nhân:
  - gọi một phim trong lịch sử là "liked" khi người dùng chấm nó 1.0–2.5 (trường hợp lỗi 3);
  - kiến thức bên ngoài lọt vào qua tính từ hoặc tiền đề ("a classic thriller", "each film has a twist").

  Verifier không nhìn thấy cả hai, vì không cái nào liên quan tới con số hay tên phim.

### Test trung thực (Honesty tests)

<!-- table:honesty -->
*Source: Honesty tests — `2026-09-27_honesty_2`*

| Test | Result |
|---|---|
| Fidelity: top driver removed → recommendation drops | 0.27 [0.10, 0.43] (n = 30) |
| Control: random history movie removed | 0.00 [0.00, 0.00] |
| Perturbation: pairs where the data flipped | 3 of 3 |
| LLM answer names the engine's top driver | 0.9 (n = 10) |
| Perturbation (graded): answer stance follows the data | 6 of 6 |
| Perturbation (graded): answers adding facts beyond tool outputs | 0 of 6 |
| Attribution (graded): stated reason matches the top driver | yes 5, partly 4, no 1 (n = 10) |
<!-- /table:honesty -->

- **Nhiễu dữ liệu (test trực tiếp cho R3).** Với ba người dùng, tôi chọn một phim họ chưa chấm (Terminator 2, Jurassic Park, Forrest Gump). Trong một bản sao của dữ liệu, điểm phim đó do 50 người dùng giống họ nhất chấm được đảo ngược (r → 5.5 − r), và tôi hỏi "what do people with similar taste think about it?" trên cả hai phiên bản. Ở cả 6 câu trả lời, lập trường đều theo dữ liệu, và không câu nào thêm thông tin ngoài output của tool. Với Terminator 2 và người dùng 1, câu trả lời trên dữ liệu thật nói "an average rating of 4.04, which is 0.55 above their own average ratings. About 71.1% of these similar users liked it". Sau khi đảo, nó nói "quite low, with an average rating of 1.46, which is 2.01 points below their own average ratings. Only about 2.6% of these similar users liked the movie". Agent không dựa vào danh tiếng của phim.
- **Độ trung thực của lời giải thích (explanation fidelity).** Tôi bỏ yếu tố chính (top driver) mà `explain` nêu ra khỏi lịch sử của người dùng rồi xếp hạng lại. Phim được gợi ý tụt ít nhất 5 bậc trong 27% trường hợp [10%, 43%]. Bỏ một phim ngẫu nhiên trong lịch sử làm điều đó trong 0% trường hợp, và việc bỏ yếu tố chính làm giảm điểm nhiều gấp 13 lần (0.091 so với 0.007). Lý do được nêu là có thật, nhưng hiếm khi tự nó quyết định, vì EASE cộng dồn trên toàn bộ lịch sử. "Because you liked X" nên được hiểu là "X là yếu tố đóng góp lớn nhất".
- **Attribution.** Lý do LLM nêu khớp với yếu tố chính của engine ở 5 trên 10 câu trả lời, khớp một phần ở 4. Câu "no" duy nhất là một câu trả lời mẫu không đưa ra lý do nào.

### Đổi model: gpt-5.1 (thử sau khi đã viết báo cáo)

Sau khi viết báo cáo, tôi chạy agent trên gpt-5.1, với `reasoning_effort: none`, thiết lập duy nhất mà ở đó model này chấp nhận temperature 0. Không gì khác thay đổi: cùng prompt, code và kịch bản. Chỉ các lần chạy dùng LLM được lặp lại, trên tập val. Để so sánh hai model mà không bị lệch do người chấm, các grader mới chấm câu trả lời của cả hai model cho cùng 29 lượt, xáo trộn, không biết model nào viết câu nào.

<!-- table:model_swap -->
*Source: Model swap on val: gpt-5.1 vs gpt-4.1-mini — `2026-09-27_agent_6` vs `2026-09-27_agent_5`*

Same prompt, code and scenarios; rubric graded blind and paired (`eval/grading/rubric_grades_blind_with_rationale.csv`).

| Measure | gpt-5.1 | gpt-4.1-mini | Difference [95% CI] | Better / same / worse |
|---|---|---|---|---|
| scenario_success | 0.75 | 0.75 | - | - |
| verifier_first_pass_rate | 0.72 | 0.76 | - | - |
| fallback_rate | 0.03 | 0.00 | - | - |
| tool_chain_accuracy | 0.97 | 1.00 | - | - |
| mean_tool_calls | 1.24 | 1.66 | - | - |
| p50_latency_ms | 4351.60 | 2732.20 | - | - |
| p95_latency_ms | 9469.14 | 5360.82 | - | - |
| rubric grounded (0–2, 29 turns) | 1.14 | 1.48 | -0.34 [-0.62, -0.07] | 3 / 15 / 11 |
| rubric relevant (0–2, 29 turns) | 2.00 | 2.00 | +0.00 [+0.00, +0.00] | 0 / 29 / 0 |
| rubric specific (0–2, 29 turns) | 1.86 | 1.72 | +0.14 [-0.07, +0.34] | 6 / 21 / 2 |
| rubric honest (0–2, 29 turns) | 1.59 | 1.76 | -0.17 [-0.41, +0.03] | 2 / 21 / 6 |
| perturbation: stance follows the data | 6 of 6 | 6 of 6 | - | - |
| perturbation: adds facts beyond tools | 1 of 6 | 0 of 6 | - | - |
| attribution: yes / partly / no | 6 / 4 / 0 | 4 / 5 / 1 | - | - |
<!-- /table:model_swap -->

- **gpt-5.1 bám dữ liệu kém hơn**, ngang bằng về độ đúng yêu cầu, và không khác biệt có ý nghĩa về độ cụ thể hay trung thực. Nó cũng chậm hơn khoảng 1.6 lần.
- **Vì sao.** Câu trả lời của gpt-5.1 nghe cụ thể hơn, nhưng chi tiết thêm vào lại đến từ chỗ sai:
  - Nó trình bày điểm trung bình của mọi người dùng như ý kiến của những người cùng gu ("similar raters give it a high mean rating of 4.16 across 93 ratings", mà không hề tra cứu người cùng gu). Lỗi này chiếm 5 trên 9 điểm 0 về grounded của nó. Verifier cho qua vì con số đó có trong output của tool.
  - Nó thêm nhiều mô tả lấy từ kiến thức riêng ("quirky, nostalgic coming-of-age story", "darkly funny").
- **Các ảnh hưởng khác.**
  - Cách diễn đạt đa dạng hơn của gpt-5.1 làm các heuristic của verifier báo nhầm. V3 từ chối một con số "2.3" đúng, và lần viết lại nói với người dùng rằng nó "not allowed to restate that number".
  - Có lần nó dùng tên Toy Story làm chữ tìm kiếm thay vì tra phim này làm phim gốc (seed).
  - V1 vẫn bắt được một ID phim mà nó lấy từ trí nhớ.
- **Quyết định: model triển khai vẫn là gpt-4.1-mini** (design D11). Một model mạnh hơn tự nó không giải quyết được việc bám dữ liệu. Cách sửa là những gì đã nêu cho trường hợp lỗi 2 và 3, cộng thêm một luật verifier: một khẳng định về "những người cùng gu" phải có lần gọi `peer_opinion` đi kèm.

### Phân tích lỗi (Failure Analysis)

Ba trường hợp dưới đây lấy từ các phiên `chat` đã chọn lọc (`transcripts/`, trace trong `traces/examples/`). Bằng chứng chỉ từ engine nằm trong `eval/results/2026-09-27_failure_evidence/`.

**1. "I liked Toy Story but I'm tired of animated movies — what else?" trả về phim về đồ chơi và Giáng sinh.**
- *Hệ thống đã gợi ý gì.* Với người dùng 15, top 5 của engine là E.T., Snatch, Toys, Santa Claus: The Movie và Jingle All the Way. Với người dùng 1 là Gremlins, Babe, Snatch, The Santa Clause và Santa Claus: The Movie.
- *Vì sao.*
  - Ở chế độ seed, feature mạnh nhất là độ giống cốt truyện với Toy Story, trọng số 0.5. Embedding cốt truyện bắt được **chủ đề** theo nghĩa đen của Toy Story (đồ chơi, trẻ em, quà Giáng sinh), không phải những phẩm chất người dùng thích (hài hước, phiêu lưu, tình bạn).
  - Toys (20 lượt chấm, trung bình 2.38), Santa Claus: The Movie (4 lượt chấm, trung bình 2.25) và Jingle All the Way lọt vào top 5 chỉ nhờ feature seed, không có đóng góp nào từ lọc cộng tác hay chất lượng.
  - `why-not --user 15 --movie "The Princess Bride" --seed 1 --exclude-genres Animation` cho `RANKED_BELOW` ở hạng 31, khoảng cách lớn nhất ở `seed`. Đóng góp lọc cộng tác (0.258) và chất lượng (0.196) của phim này mạnh, nhưng nó không nằm trong 200 cốt truyện gần nhất với Toy Story, nên thua Jingle All the Way, phim được 0.495 điểm giống cốt truyện và không có gì khác.
  - Trong các phiên dài, LLM còn thêm lỗi của riêng nó. Với người dùng 30, nó mang truy vấn của lượt trước ("dark psychological thriller with a twist") sang yêu cầu này. Với người dùng 15, nó không tra Toy Story, nên không có phim gốc nào được dùng. Sau đó nó gõ tay tên phim ở cả hai lần thử và phải dùng câu trả lời mẫu.
- *Nguyên nhân gốc.* R (feature và trọng số) và S (embedding bắt chủ đề), cộng U (sai tham số tool) ở phía agent.
- *Cách sửa.*
  - Tính độ giống với phim gốc từ dữ liệu cộng tác: chạy EASE với phim gốc làm lịch sử. Cách này tìm ra những phim mà người thích Toy Story cũng đã chấm.
  - Hoặc yêu cầu điểm cf hoặc quality tối thiểu trước khi một phim được thắng chỉ nhờ giống cốt truyện.
  - Giữ phim gốc trong state hội thoại, và xoá truy vấn trước đó khi một yêu cầu mới bắt đầu.

**2. "I want a dark psychological thriller with a twist" trả về Psycho (1960) kèm cốt truyện của một phim khác: bám dữ liệu nhưng sai.**
- *Hệ thống đã gợi ý gì.* Hạng 2 là Psycho (1960). Đoạn khớp của nó viết "a young man who prefers a lonely life. He begins to stalk a television anchor named Pavana…". Đó không phải phim năm 1960. Twelve Monkeys, hạng 3, mang cốt truyện của một phim có dàn đồng ca kiểu Hy Lạp và một nhà báo thể thao tên Lenny Weinrib. Câu trả lời gọi Psycho là "a classic crime and horror thriller" (người dùng 15, lượt 4).
- *Vì sao.*
  - Bộ dữ liệu gắn một số cốt truyện vào nhầm phim. Một đợt kiểm tra có seed trên 100 cốt truyện (50 phim được chấm nhiều nhất và 50 phim ngẫu nhiên, `eval/grading/plot_audit.csv`) tìm thấy **6 trường hợp không khớp, khoảng tin cậy 95% [2.8%, 12.5%]**. Đây là cận dưới, vì chỉ các trường hợp chắc chắn mới được tính.
  - Các trường hợp không khớp gồm cả những phim rất nổi tiếng: Seven mang cốt truyện của The Land Before Time III, Independence Day mang Day Watch, và Men in Black mang một phim chính kịch pháp đình ở Baltimore.
  - Hệ thống tin dữ liệu theo thiết kế, nên mọi kiểm tra đều qua: đoạn trích thật sự có trong dữ liệu. Trong khi đó LLM "biết" Psycho và che lấp chỗ không khớp bằng một tính từ lấy từ trí nhớ.
  - Đợt kiểm tra này là chỗ duy nhất dùng tới kiến thức bên ngoài, và chỉ để kiểm tra dữ liệu.
- *Nguyên nhân gốc.* D (dữ liệu), cộng G (kiến thức bên ngoài trong cách diễn đạt).
- *Cách sửa.*
  - Đánh dấu các cốt truyện mâu thuẫn với bằng chứng khác của phim, ví dụ vector cốt truyện nằm xa cốt truyện của các phim thường được chấm cùng, hoặc xa thể loại của phim. Hiển thị "plot may not match" thay cho đoạn trích.
  - Thêm một bước kiểm tra (một judge, hoặc rubric) cho các khẳng định mô tả mà không output nào của tool hỗ trợ.

**3. "What should I watch tonight?" nói "recommended because you liked Django Unchained", phim người dùng chấm 1.0.**
- *Hệ thống đã gợi ý gì.* Với người dùng 15, Inglourious Basterds được "recommended because you liked Inception and Django Unchained" (chấm 3.5 và **1.0**), và Good Will Hunting "because you liked … Fight Club" (chấm 2.5).
- *Vì sao.*
  - EASE được fit trên việc người dùng đã chấm những phim nào, không phải chấm bao nhiêu điểm, nên chỉ riêng việc có chấm Django Unchained đã đẩy các phim tương tự lên.
  - `because_you_rated` liệt kê các đóng góp lớn nhất bất kể điểm chấm. Output của tool có `user_rating: 1.0`, nhưng LLM diễn đạt "rated" thành "liked".
  - Verifier kiểm tra tên phim và con số, không kiểm tra động từ, nên câu trả lời được cho qua. Cùng mẫu lỗi này tạo ra ba trong sáu điểm "grounded = 0" của rubric.
- *Nguyên nhân gốc.* G (diễn đạt sai), tạo điều kiện bởi R (EASE nhị phân).
- *Cách sửa.*
  - Chỉ liệt kê làm lý do những phim trong lịch sử được chấm từ mức trung bình của chính người dùng trở lên. Cách này rẻ, nhưng làm lời giải thích kém trung thực với model hơn.
  - Hoặc fit EASE chỉ trên các tương tác "thích", việc này cần một ablation trên val.
  - Thêm một luật prompt: nói "you rated X 1.0" thay vì "you liked X".

## Nhìn lại (Reflection)

**Điều gì hoạt động tốt.**
- **Việc bám dữ liệu đứng vững ở những chỗ có thể bắt buộc.** Không phim bịa nào tới được người dùng, một ID ảo giác bị chặn, và ràng buộc được thoả mãn ở mọi lần chạy kịch bản. Test nhiễu dữ liệu cho thấy câu trả lời theo dữ liệu, không theo danh tiếng của phim.
- **Khả năng truy vết đã nhiều lần phát huy tác dụng:**
  - Việc Blend thua EASE được chẩn đoán từ phần đóng góp theo từng feature.
  - Lỗi state và lỗ hổng về độ tin cậy được xác nhận chỉ bằng cách đọc một trace cho mỗi lỗi.
  - Một báo động nhầm của verifier ("2.3 below their average" bị từ chối vì tool ghi −2.3) được test nhiễu dữ liệu phát hiện và sửa kèm các ca kiểm thử hồi quy.
- **Lõi lọc cộng tác chắc chắn và đơn giản:** một model nghiệm dạng đóng, không có vòng lặp huấn luyện, và tất định.

**Điều gì chưa tốt, và vì sao.**
- **Khám phá ngoài nhóm phim phổ biến còn yếu.** Tail recall gần 0 và phim được gợi ý phổ biến gấp đôi lịch sử của người dùng. EASE học từ việc các phim cùng xuất hiện, mà một phần ba catalog gần như không có điểm chấm.
- **Hiểu nội dung còn nông.** Cốt truyện mô tả sự kiện, embedding khớp theo chủ đề, và một số cốt truyện là của phim khác. Truy vấn về không khí và yêu cầu dựa trên phim gốc chịu ảnh hưởng nhiều nhất.
- **Cách diễn đạt của LLM là phần kém kiểm soát nhất.** Tên phim bị gõ tay thì bị bắt, nhưng tính từ từ kiến thức riêng và chữ "liked" cho điểm 1.0 thì không. Verifier chỉ bao quát được những gì kiểm tra được một cách máy móc. Một model mạnh hơn cũng không giúp được: gpt-5.1 bám dữ liệu kém hơn (xem mục đổi model).
- **Bằng chứng có giới hạn.**
  - Điểm chấm đến từ một grader LLM, không phải từ tôi.
  - Các tập nhỏ (10 truy vấn, 29 lượt).
  - Metric của agent thay đổi giữa các lần chạy giống hệt.
  - Metric offline coi phim chưa chấm là không liên quan, điều này có lợi cho phim phổ biến.

**Nếu có thêm thời gian, tôi sẽ làm gì.**
- **Sửa nhanh:**
  - độ giống phim gốc dựa trên lọc cộng tác (trường hợp lỗi 1);
  - cờ đánh dấu cốt truyện không nhất quán (trường hợp lỗi 2);
  - chỉ dùng phim được thích làm lý do, cộng một ablation EASE chỉ trên tương tác "thích" (trường hợp lỗi 3);
  - câu trả lời mẫu riêng cho từng tool.
- **Bằng chứng mạnh hơn:**
  - chạy mỗi kịch bản nhiều lần và báo cáo trung bình kèm khoảng tin cậy;
  - tự chấm lại ngẫu nhiên 20% để đo mức đồng thuận với grader LLM;
  - chấm thêm truy vấn;
  - làm một nghiên cứu người dùng nhỏ, vì metric offline không đo được mức hữu ích trong hội thoại.
- **Những thứ bị cắt khỏi thiết kế đầu tiên:** tìm kiếm lai BM25 + embedding, một cross-encoder re-ranker cho search, và một judge ở mức câu trả lời cho các khẳng định mô tả không có căn cứ, được hiệu chỉnh theo điểm chấm của chính tôi.

## Phần mở (Open Section)

**Phát hiện về dữ liệu** (tất cả từ `movie-agent validate`, trừ đợt kiểm tra cốt truyện):
- **Dữ liệu sạch:** không có điểm chấm cho phim không tồn tại, không có bản ghi trùng, không có cốt truyện dưới 100 ký tự, không thiếu năm.
- **Thể loại:** có 20 nhãn thể loại, không phải 19 như đề bài nói. `IMAX` (84 phim) là định dạng chiếu, không phải thể loại, và 3 phim có `(no genres listed)`. Cả hai bị loại khỏi phân tích gu.
- **Tag** chỉ đến từ 45 người dùng, và một người viết 1,056 trong số 2,440 tag. Tag phổ biến nhất, "in netflix queue", là danh sách việc cần làm chứ không phải mô tả. Đó là lý do tag không được dùng làm nhãn đánh giá.
- **Trùng timestamp khi chia tập:** với 120 trong 610 người dùng, ranh giới train/test rơi vào giữa một khối điểm chấm có timestamp giống hệt nhau. Thứ tự trong các khối đó là tuỳ ý, nên việc chia tập của những người dùng này một phần là ngẫu nhiên chứ không hoàn toàn theo thời gian.
- **Cốt truyện:** khoảng 6% cốt truyện mô tả một phim khác (trường hợp lỗi 2).

**Các sai lệch so với protocol đã đăng ký trước**, tất cả được ghi vào `docs/notes.md` ngay khi xảy ra:
1. Điểm search và rubric do một grader LLM chấm thay vì tôi (xem đầu báo cáo).
2. Cách chuẩn hoá trong xếp hạng và luật cho người dùng thưa dữ liệu được đổi sau lần chạy validation đầu tiên. Tập test không bị động tới, và biến thể được chọn không phải biến thể cao nhất trên val: z-score đạt 0.102 nhưng làm hỏng chế độ query.
3. Sheet search chưa chấm được đặt lại sau khi đổi bộ xếp hạng, để chỉ chấm kết quả hiện tại.
4. Một lần chạy search đầu tiên có lỗi hiển thị và chưa có điểm chấm đã bị xoá và chạy lại.
5. Sau khi viết báo cáo, các lần chạy agent và honesty được lặp lại với gpt-5.1 trên tập val (mục đổi model). Không dùng dữ liệu test nào, và model triển khai không thay đổi.

Tập test được đánh giá đúng một lần, từ một commit sạch (`eval/results/test_runs.log`).

**Chi phí và tốc độ.** gpt-4.1-mini dùng khoảng 7k token mỗi lượt. Độ trễ trung vị 2.6–2.9 s và phân vị 95 là 4.7–5.8 s, đã gồm bước kiểm tra và thỉnh thoảng một lần viết lại.

**Công cụ đã dùng.** Code được viết bằng Claude Code. Việc chấm điểm bằng LLM và đợt kiểm tra cốt truyện do các subagent Claude thực hiện. Bản thân trợ lý chạy trên OpenAI gpt-4.1-mini. Thiết kế, các quyết định và bằng chứng của chúng nằm trong `docs/design.md` và `docs/notes.md`.
