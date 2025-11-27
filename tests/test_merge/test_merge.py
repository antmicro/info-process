import pytest
from info_process.merge import strip_test_name_simple, strip_test_name_regex

simple_strip_data = [
    (("./folder/some_file_name.info", ".info,./folder/"), "some_file_name"),
    ((r"/src/folder/nested_folder/.pReFiX\ somefile.suffix", r".pReFiX\ ,.suffix"), "/src/folder/nested_folder/somefile"),
]

regex_strip_data = [
    (("./folder/some_blabla_numbers_name.info", r"_([a-z]+_)|_name|\.info" ),"./folder/some_numbers"),
    (("./ctlr_module.yml_dir/simulation.12345.info", r"^(\./).*\.(.*\.)\d+|.info"), "ctlr_module.12345"),
    (("./unique_123_reg.info",r".info|_(\d+_)"), "./unique_reg"),
    (("./unique_123_reg.info",r".info|_(\d+_)"), "./unique_reg"),
    (("aaabbb","ab"), "aabb"),
    (("a_b_c_d_e","_._"), "ace")
]

@pytest.mark.parametrize("inputs,expected", simple_strip_data)
def test_simple_strip(inputs, expected):
    result = strip_test_name_simple(*inputs)
    assert result == expected

@pytest.mark.parametrize("inputs,expected", regex_strip_data)
def test_simple_strip(inputs, expected):
    result = strip_test_name_regex(*inputs)
    assert result == expected
