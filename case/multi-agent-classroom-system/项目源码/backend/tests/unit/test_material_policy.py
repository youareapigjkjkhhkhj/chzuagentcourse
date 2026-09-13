"""上传前的几道闸门：内容与后缀对不对得上（F4-1 / P4-B2 / P4-F1）。

只测 `check_magic` 这一道 —— 它只读文件头、不碰库也不碰配置，是这几道闸门里
唯一能独立拉出来测的。另外几道（大小上限、开关、并发）都要 app 上下文，
跟着 `test_material_store.py` 与 `tests/contract/test_p4_material_api.py` 走。

**为什么「样本切在半个字上」要单独立一条**：`PROBE_BYTES = 4096` 不是 3 的倍数，
而 UTF-8 一个汉字 3 字节 —— 随便一份中文讲义都有三分之二的概率被切在字中间。
判据要是写成「样本必须严格解得开」，这些讲义就会在**上传这一步**被拒，
连解析都轮不到。这条用例把这个坑钉住。
"""

from __future__ import annotations

import pytest

from app.common.errors import UnsupportedMediaError
from app.services.materials import policy

pytestmark = pytest.mark.unit


def _write(tmp_path, raw: bytes, name: str = "讲义.txt"):
    path = tmp_path / name
    path.write_bytes(raw)
    return path


def test_a_utf8_file_whose_probe_cuts_a_character_is_still_text(tmp_path):
    """样本正好切在半个汉字上，仍然是一份合格的 UTF-8 讲义（P4-B1）。"""
    raw = "倒排索引".encode("utf-8") * 400  # 12 字节的整数倍 → 4096 处必然切在字中间
    head = raw[: policy.PROBE_BYTES]
    with pytest.raises(UnicodeDecodeError):
        head.decode("utf-8")  # 这正是严格判据会误判的那一下

    policy.check_magic(_write(tmp_path, raw), ".txt")  # 不该抛


def test_a_real_gbk_file_is_accepted(tmp_path):
    """GBK 的讲义也是讲义：放宽尾部不能把 GBK 那条路堵死。"""
    raw = "梯度下降与倒排索引。".encode("gbk") * 300
    with pytest.raises(UnicodeDecodeError):
        raw[: policy.PROBE_BYTES].decode("utf-8")  # UTF-8 解不开，得靠 GBK 那条路

    policy.check_magic(_write(tmp_path, raw), ".txt")


def test_a_stray_byte_is_not_excused_as_a_half_character(tmp_path):
    """`\\xff` 不是「切在半个字上」，是「这不是文本」（P4-B2）。

    放松尾部只该放过「一个字符还没收全」；`\\xff` 压根不是任何字符的开头。
    「依次去掉末尾 0~3 字节再试」那种写法会把它当成切了半个字——去掉那 1 个
    字节就剩空串，空串当然解得开。这条用例把那条界线钉住。
    """
    policy.check_magic(_write(tmp_path, "中文讲义".encode("utf-8") * 40), ".txt")  # 正常的那份不该受影响

    with pytest.raises(UnsupportedMediaError):
        policy.check_magic(_write(tmp_path, b"\xff\xff\xff", name="坏.txt"), ".txt")


def test_a_binary_file_renamed_to_txt_is_rejected(tmp_path):
    """带 NUL 的二进制（.exe / .zip 改名）一律拒，提示它其实是老式 Office 格式。"""
    ole = policy.OLE_MAGIC + b"\x00" * 128
    with pytest.raises(UnsupportedMediaError) as info:
        policy.check_magic(_write(tmp_path, ole), ".txt")

    assert "老式" in str(info.value)


def test_a_pdf_that_is_actually_text_is_rejected(tmp_path):
    """后缀写着 .pdf、内容却是纯文本：415 并说清是后缀不对。"""
    path = _write(tmp_path, "这是一段纯文本。".encode("utf-8") * 20, name="其实是文本.pdf")
    with pytest.raises(UnsupportedMediaError) as info:
        policy.check_magic(path, ".pdf")

    assert "后缀" in str(info.value)


def test_an_old_doc_gets_told_what_to_save_as():
    """.doc 拒了要给出下一步（「另存为 .docx」），不能只说一句「不支持」。

    它走的是**后缀白名单**这道闸门（`check_magic` 只处理白名单里的四种），
    也就是用户真的会撞上的那一条。
    """
    with pytest.raises(UnsupportedMediaError) as info:
        policy.ensure_supported(".doc")

    assert ".docx" in str(info.value)
