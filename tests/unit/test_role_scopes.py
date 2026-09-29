

def test_answer_predictor_can_read_its_own_stage_inputs():
    """S0.3 instructs the predictor to read 题面契约 AND 数据档案; the role's
    read scopes must cover both (real-provider gate found the gap: the leg was
    unsatisfiable as prompted)."""
    from mmagent.mm.roles.registry import get_role

    role = get_role("answer_predictor")
    scopes = role.read_scopes
    assert "交接/题面契约.json" in scopes
    assert "交接/数据档案.json" in scopes


def test_reader_can_enumerate_input_directories_before_reading():
    """S0 Reader must discover actual filenames instead of guessing directory/file names."""
    from mmagent.mm.roles.registry import get_role

    role = get_role("reader")
    assert "fs.list" in role.allowed_tools
    assert "输入/**" in role.read_scopes
