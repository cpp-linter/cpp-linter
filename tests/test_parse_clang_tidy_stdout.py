import pytest
from cpp_linter.clang_tools.clang_tidy import parse_tidy_output

TIDY_OUT = """
/home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:46:19: error: use of undeclared identifier 'readFreeImageTexture' [clang-diagnostic-error]
   46 |            return readFreeImageTexture(reader);
      |                   ^
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:659:32: note: in instantiation of function template specialization 'tb::mdl::(anonymous namespace)::loadTexture(const std::string &)::(anonymous class)::operator()<std::shared_ptr<tb::fs::File>>' requested here
  659 |     using Fn_Result = decltype(f(std::declval<Value&&>()));
      |                                ^
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:2949:29: note: in instantiation of function template specialization 'kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>::and_then<(lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)>' requested here
 2949 |   return std::forward<R>(r).and_then(t.and_then);
      |                             ^
/home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:32: note: in instantiation of function template specialization 'kdl::detail::operator|<kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>, (lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)>' requested here
   44 |   return diskFS.openFile(name) | kdl::and_then([](const auto& file) {
      |                                ^
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:661:19: error: static assertion failed due to requirement 'is_result_v<int>': Function must return a result type [clang-diagnostic-error]
  661 |     static_assert(is_result_v<Fn_Result>, "Function must return a result type");
      |                   ^~~~~~~~~~~~~~~~~~~~~~
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:2949:29: note: in instantiation of function template specialization 'kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>::and_then<(lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)>' requested here
 2949 |   return std::forward<R>(r).and_then(t.and_then);
      |                             ^
/home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:32: note: in instantiation of function template specialization 'kdl::detail::operator|<kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>, (lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)>' requested here
   44 |   return diskFS.openFile(name) | kdl::and_then([](const auto& file) {
      |                                ^
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:663:77: error: no type named 'type' in 'kdl::detail::chain_results<kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>, int>' [clang-diagnostic-error]
  663 |     using Cm_Result = typename detail::chain_results<My_Result, Fn_Result>::type;
      |                       ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^~~~
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:667:48: error: no matching function for call to object of type 'const (lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)' [clang-diagnostic-error]
  667 |         [&](value_type&& v) { return Cm_Result{f(std::move(v))}; },
      |                                                ^
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:667:29: note: while substituting into a lambda expression here
  667 |         [&](value_type&& v) { return Cm_Result{f(std::move(v))}; },
      |                             ^
/home/runner/work/TrenchBroom/TrenchBroom/lib/KdLib/include/kd/result.h:2949:29: note: in instantiation of function template specialization 'kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>::and_then<(lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)>' requested here
 2949 |   return std::forward<R>(r).and_then(t.and_then);
      |                             ^
/home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:32: note: in instantiation of function template specialization 'kdl::detail::operator|<kdl::result<std::shared_ptr<tb::fs::File>, kdl::result_error>, (lambda at /home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48)>' requested here
   44 |   return diskFS.openFile(name) | kdl::and_then([](const auto& file) {
      |                                ^
/home/runner/work/TrenchBroom/TrenchBroom/common/test/src/mdl/tst_ReadFreeImageTexture.cpp:44:48: note: candidate template ignored: substitution failure [with file:auto = typename std::remove_reference<shared_ptr<File> &>::type]
   44 |   return diskFS.openFile(name) | kdl::and_then([](const auto& file) {
      |                                                ^
"""


@pytest.mark.no_clang
def test_parse_clang_tidy_output() -> None:
    """parsing of clang-tidy output to validate the regex patterns used."""
    advice = parse_tidy_output(TIDY_OUT, database=None)

    assert len(advice.notes) == 4
    for note in advice.notes:
        assert " " not in note.diagnostic
        assert "-" in note.diagnostic
