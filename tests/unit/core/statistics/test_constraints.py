import json

import pandas as pd
import pytest

from whylogs.app.config import load_config
from whylogs.app.session import session_from_config
from whylogs.core.statistics.constraints import (
    DatasetConstraints,
    Op,
    SummaryConstraint,
    ValueConstraint,
    _summary_funcs1,
    _value_funcs,
    maxBetweenConstraint,
    meanBetweenConstraint,
    minBetweenConstraint,
    stddevBetweenConstraint,
    containsEmailConstraint,
    containsCreditCardConstraint
)
from whylogs.proto import Op
from whylogs.util.protobuf import message_to_json


def test_value_summary_serialization():

    for each_op, _ in _value_funcs.items():

        value = ValueConstraint(each_op, 3.6)
        msg_value = value.to_protobuf()
        json_value = json.loads(message_to_json(msg_value))
        assert json_value["name"] == "value " + Op.Name(each_op) + " 3.6"
        assert pytest.approx(json_value["value"], 0.001) == 3.6
        assert json_value["op"] == Op.Name(each_op)
        assert json_value["verbose"] == False

    for each_op, _ in _summary_funcs1.items():
        if each_op == Op.BTWN:
            continue
        # constraints may have an optional name
        sum_constraint = SummaryConstraint("min", each_op, 300000, name="< 30K")
        msg_sum_const = sum_constraint.to_protobuf()
        json_summary = json.loads(message_to_json(msg_sum_const))

        assert json_summary["name"] == "< 30K"
        assert pytest.approx(json_summary["value"], 0.1) == 300000
        assert json_summary["firstField"] == "min"
        assert json_summary["op"] == str(Op.Name(each_op))
        assert json_summary["verbose"] == False


def test_value_constraints(df_lending_club, local_config_path):

    conforming_loan = ValueConstraint(Op.LT, 548250)
    smallest_loan = ValueConstraint(Op.GT, 2500.0, verbose=True)

    high_fico = ValueConstraint(Op.GT, 4000)

    dc = DatasetConstraints(None, value_constraints={"loan_amnt": [conforming_loan, smallest_loan], "fico_range_high": [high_fico]})

    config = load_config(local_config_path)
    session = session_from_config(config)

    profile = session.log_dataframe(df_lending_club, "test.data", constraints=dc)
    session.close()
    report = dc.report()

    assert len(report) == 2
    print(report)
    # make sure it checked every value
    for each_feat in report:
        for each_constraint in each_feat[1]:
            assert each_constraint[1] == 50

    assert report[1][1][0][2] == 50


def test_value_constraints_pattern_match(df_lending_club, local_config_path):

    regex_state_abbreviation = r"^[a-zA-Z]{2}$"
    contains_state = ValueConstraint(Op.MATCH, regex_pattern=regex_state_abbreviation)

    regex_date = r"^[a-zA-Z]{3}-[0-9]{4}$"
    not_contains_date = ValueConstraint(Op.NOMATCH, regex_pattern=regex_date)

    # just to test applying regex patterns on non-string values
    contains_state_loan_amnt = ValueConstraint(Op.MATCH, regex_pattern=regex_state_abbreviation)

    dc = DatasetConstraints(
        None, value_constraints={"addr_state": [contains_state], "earliest_cr_line": [not_contains_date], "loan_amnt": [contains_state_loan_amnt]}
    )

    config = load_config(local_config_path)
    session = session_from_config(config)

    profile = session.log_dataframe(df_lending_club, "test.data", constraints=dc)
    session.close()
    report = dc.report()
    # checks there are constraints for 3 features
    assert len(report) == 3
    print(report)
    # make sure it checked every value
    for each_feat in report:
        for each_constraint in each_feat[1]:
            assert each_constraint[1] == 50

    # Every row should match a state abbreviation
    assert report[0][1][0][2] == 0

    # At least 1 should be a match w/ the given pattern (# of failures of NOMATCH = # Matches)
    assert report[1][1][0][2] > 0

    # Every row should be a failure, because "loan_amnt" is not a string type
    assert report[2][1][0][2] == 50


def test_summary_constraints(df_lending_club, local_config_path):
    non_negative = SummaryConstraint("min", Op.GE, 0)

    dc = DatasetConstraints(None, summary_constraints={"annual_inc": [non_negative]})
    config = load_config(local_config_path)
    session = session_from_config(config)
    profile = session.log_dataframe(df_lending_club, "test.data", constraints=dc)
    session.close()
    report = r = profile.apply_summary_constraints()

    assert len(report) == 1
    # make sure it checked every value
    for each_feat in report:
        for each_constraint in each_feat[1]:
            assert each_constraint[1] == 1


def test_value_constraints_no_merge_different_names():
    constraint1 = ValueConstraint(Op.LT, 1, name="c1")
    constraint2 = ValueConstraint(Op.LT, 1, name="c2")
    with pytest.raises(AssertionError):
        constraint1.merge(constraint2)


def test_value_constraints_no_merge_different_values():
    constraint1 = ValueConstraint(Op.LT, 1)
    constraint2 = ValueConstraint(Op.LT, 2)
    with pytest.raises(AssertionError):
        constraint1.merge(constraint2)


def test_summary_constraints_no_merge_different_names():
    constraint1 = SummaryConstraint("min", Op.GE, 0, name="non-negative")
    constraint2 = SummaryConstraint("min", Op.GE, 0, name="positive-number")
    with pytest.raises(AssertionError):
        constraint1.merge(constraint2)


def test_summary_constraints_no_merge_different_values():
    constraint1 = SummaryConstraint("min", Op.GE, 1, name="GreaterThanThreshold")
    constraint2 = SummaryConstraint("min", Op.GE, 2, name="GreaterThanThreshold")
    with pytest.raises(AssertionError):
        constraint1.merge(constraint2)


def test_value_constraints_merge():
    constraint1 = ValueConstraint(Op.LT, 1)
    constraint2 = ValueConstraint(Op.LT, 1)
    merged = constraint1.merge(constraint2)
    assert merged.report() == ("value LT 1", 0, 0), "merging unlogged constraints should not change them from initiat state"


def test_value_constraints_merge_empty():
    constraint1 = ValueConstraint(Op.LT, 1)
    constraint2 = None
    merged = constraint1.merge(constraint2)
    assert merged == constraint1, "merging empty constraints should preserve left hand side"


def test_summary_between_serialization_deserialization():

    # constraints may have an optional name
    sum_constraint = SummaryConstraint("min", Op.BTWN, 0.1, 2.4)
    msg_sum_const = sum_constraint.to_protobuf()
    json_summary = json.loads(message_to_json(msg_sum_const))

    assert json_summary["name"] == "summary min BTWN 0.1 and 2.4"
    assert pytest.approx(json_summary["between"]["lowerValue"], 0.1) == 0.1
    assert pytest.approx(json_summary["between"]["upperValue"], 0.1) == 2.4
    assert json_summary["firstField"] == "min"
    assert json_summary["op"] == str(Op.Name(Op.BTWN))
    assert json_summary["verbose"] == False

    sum_deser_constraint = SummaryConstraint.from_protobuf(sum_constraint.to_protobuf())

    json_deser_summary = json.loads(message_to_json(sum_deser_constraint.to_protobuf()))

    assert json_summary["name"] == json_deser_summary["name"]
    assert pytest.approx(json_summary["between"]["lowerValue"], 0.001) == pytest.approx(json_deser_summary["between"]["lowerValue"], 0.001)
    assert pytest.approx(json_summary["between"]["upperValue"], 0.001) == pytest.approx(json_deser_summary["between"]["upperValue"], 0.001)
    assert json_summary["firstField"] == json_deser_summary["firstField"]
    assert json_summary["op"] == json_deser_summary["op"]
    assert json_summary["verbose"] == json_deser_summary["verbose"]


def test_summary_between_constraint_incompatible_parameters():
    with pytest.raises(TypeError):
        SummaryConstraint("min", Op.BTWN, 0.1, "stddev")

    with pytest.raises(ValueError):
        SummaryConstraint("min", Op.BTWN, 0.1, second_field="stddev")

    with pytest.raises(ValueError):
        SummaryConstraint("min", Op.BTWN, 0.1, 2.4, "stddev")

    with pytest.raises(ValueError):
        SummaryConstraint("min", Op.BTWN, 0.1, 2.4, third_field="stddev")

    with pytest.raises(TypeError):
        SummaryConstraint("stddev", Op.BTWN, second_field=2, third_field="max")

    with pytest.raises(TypeError):
        SummaryConstraint("stddev", Op.BTWN, 2, "max")


def _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, between_constraint):
    min_gt_constraint = SummaryConstraint("min", Op.GT, value=100)
    max_le_constraint = SummaryConstraint("max", Op.LE, value=5)

    dc = DatasetConstraints(None, summary_constraints={"annual_inc": [between_constraint, max_le_constraint], "loan_amnt": [min_gt_constraint]})
    config = load_config(local_config_path)
    session = session_from_config(config)
    profile = session.log_dataframe(df_lending_club, "test.data", constraints=dc)
    session.close()
    report = profile.apply_summary_constraints()

    print(report)
    assert len(report) == 2

    # make sure it checked every value
    for each_feat in report:
        for each_constraint in each_feat[1]:
            assert each_constraint[1] == 1


def test_summary_between_constraints_values(df_lending_club, local_config_path):
    std_dev_between = SummaryConstraint("stddev", Op.BTWN, value=100, upper_value=200)
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, std_dev_between)


def test_summary_between_constraints_fields(df_lending_club, local_config_path):
    std_dev_between = SummaryConstraint("stddev", Op.BTWN, second_field="mean", third_field="max")
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, std_dev_between)


def test_summary_between_constraints_no_merge_different_values_fields():

    std_dev_between1 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=200)
    std_dev_between2 = SummaryConstraint("stddev", Op.BTWN, value=0.2, upper_value=200)

    with pytest.raises(AssertionError):
        std_dev_between1.merge(std_dev_between2)

    std_dev_between1 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=200)
    std_dev_between2 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=300)

    with pytest.raises(AssertionError):
        std_dev_between1.merge(std_dev_between2)

    std_dev_between1 = SummaryConstraint("stddev", Op.BTWN, second_field="min", third_field="max")
    std_dev_between2 = SummaryConstraint("stddev", Op.BTWN, second_field="mean", third_field="max")

    with pytest.raises(AssertionError):
        std_dev_between1.merge(std_dev_between2)

    std_dev_between1 = SummaryConstraint("stddev", Op.BTWN, second_field="min", third_field="mean")
    std_dev_between2 = SummaryConstraint("stddev", Op.BTWN, second_field="min", third_field="max")

    with pytest.raises(AssertionError):
        std_dev_between1.merge(std_dev_between2)


def test_summary_between_constraints_no_merge_different_names():
    std_dev_between1 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=200, name="std dev between 1")
    std_dev_between2 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=200, name="std dev between 2")

    with pytest.raises(AssertionError):
        std_dev_between1.merge(std_dev_between2)


def test_summary_between_constraints_merge():
    std_dev_between1 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=200)
    std_dev_between2 = SummaryConstraint("stddev", Op.BTWN, value=0.1, upper_value=200)

    merged = std_dev_between1.merge(std_dev_between2)

    pre_merge_json = json.loads(message_to_json(std_dev_between1.to_protobuf()))
    merge_json = json.loads(message_to_json(merged.to_protobuf()))

    assert pre_merge_json["name"] == merge_json["name"]
    assert pytest.approx(pre_merge_json["between"]["lowerValue"], 0.001) == pytest.approx(merge_json["between"]["lowerValue"], 0.001)
    assert pytest.approx(pre_merge_json["between"]["upperValue"], 0.001) == pytest.approx(merge_json["between"]["upperValue"], 0.001)
    assert pre_merge_json["firstField"] == merge_json["firstField"]
    assert pre_merge_json["op"] == merge_json["op"]
    assert pre_merge_json["verbose"] == merge_json["verbose"]


def test_stddev_between_constraint_value(df_lending_club, local_config_path):
    lower = 2.3
    upper = 5.4
    stddev_between_values = stddevBetweenConstraint(lower_value=lower, upper_value=upper)
    # check if all constraints are applied
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_values)


def test_stddev_between_constraint_field(df_lending_club, local_config_path):
    lower = "min"
    upper = "max"
    stddev_between_fields = stddevBetweenConstraint(lower_field=lower, upper_field=upper)
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_fields)


def test_stddev_between_constraint_invalid():
    with pytest.raises(ValueError):
        stddevBetweenConstraint(lower_value=2)
    with pytest.raises(ValueError):
        stddevBetweenConstraint(lower_field="min")
    with pytest.raises(TypeError):
        stddevBetweenConstraint(lower_value="2", upper_value=2)
    with pytest.raises(TypeError):
        stddevBetweenConstraint(lower_field="max", upper_field=2)


def test_mean_between_constraint_value(df_lending_club, local_config_path):
    lower = 2.3
    upper = 5.4
    stddev_between_values = meanBetweenConstraint(lower_value=lower, upper_value=upper)
    # check if all constraints are applied
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_values)


def test_mean_between_constraint_field(df_lending_club, local_config_path):
    lower = "min"
    upper = "max"
    stddev_between_fields = meanBetweenConstraint(lower_field=lower, upper_field=upper)
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_fields)


def test_mean_between_constraint_invalid():
    with pytest.raises(ValueError):
        meanBetweenConstraint(lower_value=2)
    with pytest.raises(ValueError):
        meanBetweenConstraint(lower_field="min")
    with pytest.raises(TypeError):
        meanBetweenConstraint(lower_value="2", upper_value=2)
    with pytest.raises(TypeError):
        meanBetweenConstraint(lower_field="max", upper_field=2)


def test_min_between_constraint_value(df_lending_club, local_config_path):
    lower = 2.3
    upper = 5.4
    stddev_between_values = minBetweenConstraint(lower_value=lower, upper_value=upper)
    # check if all constraints are applied
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_values)


def test_min_between_constraint_field(df_lending_club, local_config_path):
    lower = "stddev"
    upper = "max"
    stddev_between_fields = minBetweenConstraint(lower_field=lower, upper_field=upper)
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_fields)


def test_min_between_constraint_invalid():
    with pytest.raises(ValueError):
        minBetweenConstraint(lower_value=2)
    with pytest.raises(ValueError):
        minBetweenConstraint(lower_field="min")
    with pytest.raises(TypeError):
        minBetweenConstraint(lower_value="2", upper_value=2)
    with pytest.raises(TypeError):
        minBetweenConstraint(lower_field="max", upper_field=2)


def test_max_between_constraint_value(df_lending_club, local_config_path):
    lower = 2.3
    upper = 5.4
    stddev_between_values = maxBetweenConstraint(lower_value=lower, upper_value=upper)
    # check if all constraints are applied
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_values)


def test_max_between_constraint_field(df_lending_club, local_config_path):
    lower = "stddev"
    upper = "mean"
    stddev_between_fields = maxBetweenConstraint(lower_field=lower, upper_field=upper)
    _apply_between_summary_constraint_on_dataset(df_lending_club, local_config_path, stddev_between_fields)


def test_max_between_constraint_invalid():
    with pytest.raises(ValueError):
        maxBetweenConstraint(lower_value=2)
    with pytest.raises(ValueError):
        maxBetweenConstraint(lower_field="min")
    with pytest.raises(TypeError):
        maxBetweenConstraint(lower_value="2", upper_value=2)
    with pytest.raises(TypeError):
        maxBetweenConstraint(lower_field="max", upper_field=2)


def _report_email_value_constraint_on_data_set(local_config_path, pattern=None):
    df = pd.DataFrame([
        {'email': r"abc's@gmail.com"},
        {'email': r'"avrrr test \@"@gmail.com'},
        {'email': r'abc..q12@example.us'},
        {'email': r'"sdsss\d"@gmail.com'},
        {'email': r'customer/department=shipping?@example-another.some-other.us'},
        {'email': r'.should_fail@yahoo.com'}
    ])

    email_constraint = containsEmailConstraint(regex_pattern=pattern)
    dc = DatasetConstraints(None, value_constraints={"email": [email_constraint]})
    config = load_config(local_config_path)
    session = session_from_config(config)
    profile = session.log_dataframe(df, "test.data", constraints=dc)
    session.close()
    report = dc.report()
    return report


def test_email_constraint(local_config_path):
    report = _report_email_value_constraint_on_data_set(local_config_path)

    assert report[0][1][0][1] == 6
    assert report[0][1][0][2] == 2


def test_email_constraint_supply_regex_pattern(local_config_path):
    report = _report_email_value_constraint_on_data_set(local_config_path, r'\S+@\S+')
    assert report[0][1][0][0] == rf'value {Op.Name(Op.MATCH)} \S+@\S+'
    assert report[0][1][0][1] == 6
    assert report[0][1][0][2] == 1


#fails
# def test_email_constraint_merge_valid():
#     ec1 = emailConstraint(regex_pattern=r'\S+@\S+')
#     ec2 = emailConstraint(regex_pattern=r'\S+@\S+')
#     merged = ec1.merge(ec2)
#     print(merged.to_protobuf())

def _report_credit_card_value_constraint_on_data_set(local_config_path, regex_pattern=None):
    df = pd.DataFrame([
        {'credit_card': '3714-496353-98431'},
        {'credit_card': '3787 344936 71000'},
        {'credit_card': '3056 930902 5904'},
        {'credit_card': '3065 133242 2899'},
        {'credit_card': '3852-000002-3237'},
        {'credit_card': '6011 1111 1111 1117'},
        {'credit_card': '6011-0009-9013-9424'},
        {'credit_card': '3530 1113 3330 0000'},
        {'credit_card': '3566-0020-2036-0505'},
        {'credit_card': '5555 5555 5555 4444'},
        {'credit_card': '5105 1051 0510 5100'},
        {'credit_card': '4111 1111 1111 1111'},
        {'credit_card': '4012 8888 8888 1881'},
        {'credit_card': '4222-2222-2222-2222'},
        {'credit_card': '1111-1111-1111-1111'},
        {'credit_card': 'a4111 1111 1111 1111b'},
        {'credit_card': '4111111111111111'},
        # maybe this should pass in a normal scenario, currently it is converted to integer
        {'credit_card': 12345},
        {'credit_card': 'absfcvs'}
    ])

    credit_card_constraint = containsCreditCardConstraint(regex_pattern=regex_pattern)
    dc = DatasetConstraints(None, value_constraints={"credit_card": [credit_card_constraint]})
    config = load_config(local_config_path)
    session = session_from_config(config)
    profile = session.log_dataframe(df, "test.data", constraints=dc)
    session.close()
    return dc.report()


def test_credit_card_constraint(local_config_path):
    report = _report_credit_card_value_constraint_on_data_set(local_config_path)
    assert report[0][1][0][1] == 19
    assert report[0][1][0][2] == 6


def test_credit_card_constraint_supply_regex_pattern(local_config_path):
    report = _report_credit_card_value_constraint_on_data_set(local_config_path, r'^(?:[0-9]{4}[\s-]?){3,4}$')
    print(report)
    assert report[0][1][0][0] == rf'value {Op.Name(Op.MATCH)} ' + r'^(?:[0-9]{4}[\s-]?){3,4}$'
    assert report[0][1][0][1] == 19
    assert report[0][1][0][2] == 9