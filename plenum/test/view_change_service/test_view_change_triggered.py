from functools import partial

import pytest
from plenum.test.delayers import cDelay
from plenum.common.messages.internal_messages import NeedViewChange
from plenum.server.consensus.ordering_service_msg_validator import OrderingServiceMsgValidator
from plenum.server.consensus.primary_selector import RoundRobinPrimariesSelector
from plenum.test.delayers import cDelay
from plenum.test.helper import checkViewNoForNodes, sdk_send_random_and_check
from plenum.test.node_catchup.helper import ensure_all_nodes_have_same_data
from plenum.test.helper import checkViewNoForNodes, sdk_send_random_and_check, assertExp
from plenum.test.node_request.helper import sdk_ensure_pool_functional
from plenum.test.pool_transactions.helper import disconnect_node_and_ensure_disconnected
from plenum.test.stasher import delay_rules_without_processing
from plenum.test.test_node import ensureElectionsDone, getNonPrimaryReplicas

from stp_core.common.log import Logger
from stp_core.loop.eventually import eventually


REQ_COUNT = 10


@pytest.fixture(scope="module")
def tconf(tconf):
    old_new_view_timeout = tconf.NEW_VIEW_TIMEOUT
    old_batch_size = tconf.Max3PCBatchSize
    tconf.NEW_VIEW_TIMEOUT = 5
    tconf.Max3PCBatchSize = 1
    yield tconf
    tconf.Max3PCBatchSize = old_batch_size
    tconf.NEW_VIEW_TIMEOUT = old_new_view_timeout


@pytest.fixture(scope="module")
def txnPoolNodeSet(txnPoolNodeSet):
    for node in txnPoolNodeSet:
        for replica in node.replicas.values():
            replica._ordering_service._validator = OrderingServiceMsgValidator(replica._consensus_data)
        node._view_changer.start_view_change = partial(trigger_view_change_on_node, node)
    yield txnPoolNodeSet


def trigger_view_change_on_node(node, proposed_view_no):
    for r in node.replicas.values():
        r.internal_bus.send(NeedViewChange(proposed_view_no))
        if r.isMaster:
            assert r._consensus_data.waiting_for_new_view


def trigger_view_change(txnPoolNodeSet, proposed_view_no):
    for node in txnPoolNodeSet:
        trigger_view_change_on_node(node, proposed_view_no)


def get_next_primary_name(txnPoolNodeSet, expected_view_no):
    selector = RoundRobinPrimariesSelector()
    inst_count = len(txnPoolNodeSet[0].replicas)
    next_p_name = selector.select_primaries(expected_view_no, inst_count, txnPoolNodeSet[0].poolManager.node_names_ordered_by_rank())[0]
    return next_p_name


def test_view_change_triggered(looper, txnPoolNodeSet, sdk_pool_handle, sdk_wallet_client):
    current_view_no = checkViewNoForNodes(txnPoolNodeSet)
    trigger_view_change(txnPoolNodeSet, current_view_no + 1)
    ensureElectionsDone(looper, txnPoolNodeSet)
    sdk_ensure_pool_functional(looper, txnPoolNodeSet, sdk_wallet_client, sdk_pool_handle)


def test_view_change_triggered_after_ordering(looper, txnPoolNodeSet, sdk_pool_handle, sdk_wallet_client):
    sdk_send_random_and_check(looper, txnPoolNodeSet, sdk_pool_handle, sdk_wallet_client, REQ_COUNT)
    current_view_no = checkViewNoForNodes(txnPoolNodeSet)
    trigger_view_change(txnPoolNodeSet, current_view_no + 1)
    ensureElectionsDone(looper, txnPoolNodeSet)
    sdk_ensure_pool_functional(looper, txnPoolNodeSet, sdk_wallet_client, sdk_pool_handle)


def test_view_change_with_next_primary_stopped(looper, txnPoolNodeSet, sdk_pool_handle, sdk_wallet_client):
    old_view_no = checkViewNoForNodes(txnPoolNodeSet)
    next_primary = get_next_primary_name(txnPoolNodeSet, old_view_no + 1)
    disconnect_node_and_ensure_disconnected(looper, txnPoolNodeSet, next_primary)
    remaining_nodes = [node for node in txnPoolNodeSet if node.name != next_primary]
    trigger_view_change(remaining_nodes, old_view_no + 1)
    ensureElectionsDone(looper, remaining_nodes, instances_list=range(2), customTimeout=15)
    sdk_ensure_pool_functional(looper, remaining_nodes, sdk_wallet_client, sdk_pool_handle)
    current_view_no = checkViewNoForNodes(remaining_nodes)
    assert current_view_no == old_view_no + 2


def test_view_change_with_next_primary_stopped_and_one_node_lost_commit(looper,
                                                                        txnPoolNodeSet,
                                                                        sdk_pool_handle,
                                                                        sdk_wallet_client):
    old_view_no = checkViewNoForNodes(txnPoolNodeSet)
    next_primary = get_next_primary_name(txnPoolNodeSet, old_view_no + 1)
    slow_node = [r.node for r in getNonPrimaryReplicas(txnPoolNodeSet) if r.node.name != next_primary][0]
    last_pp_seq_no = slow_node.master_last_ordered_3PC[1]

    with delay_rules_without_processing(slow_node.nodeIbStasher, cDelay()):
        sdk_send_random_and_check(looper, txnPoolNodeSet, sdk_pool_handle, sdk_wallet_client, 1)
        looper.run(eventually(lambda preprepared: assertExp(any(last_pp_seq_no + 1 == bid.pp_seq_no
                                                                for bid in preprepared)),
                              slow_node.master_replica._consensus_data.preprepared))

    disconnect_node_and_ensure_disconnected(looper, txnPoolNodeSet, next_primary)
    trigger_view_change(txnPoolNodeSet, old_view_no + 1)
    ensureElectionsDone(looper, txnPoolNodeSet)
    sdk_ensure_pool_functional(looper, txnPoolNodeSet, sdk_wallet_client, sdk_pool_handle)
    ensure_all_nodes_have_same_data(looper, txnPoolNodeSet)


def test_view_change_with_next_primary_stopped_and_one_node_lost_commit(looper, txnPoolNodeSet,
                                                                        sdk_pool_handle, sdk_wallet_client,
                                                                        limitTestRunningTime):
    current_view_no = checkViewNoForNodes(txnPoolNodeSet)
    next_primary = get_next_primary_name(txnPoolNodeSet, current_view_no + 1)
    # delayed_node = [r.node for r in getNonPrimaryReplicas(txnPoolNodeSet) if r.node.name != next_primary][0]
    delayed_node = txnPoolNodeSet[-1]
    other_nodes = [n for n in txnPoolNodeSet if n.name != next_primary]

    with delay_rules_without_processing(delayed_node.nodeIbStasher, cDelay()):
        sdk_send_random_and_check(looper, txnPoolNodeSet, sdk_pool_handle, sdk_wallet_client, 2)

        disconnect_node_and_ensure_disconnected(looper, txnPoolNodeSet, next_primary)
        trigger_view_change(txnPoolNodeSet, current_view_no + 1)

    ensureElectionsDone(looper, other_nodes,
                        instances_list=range(2), customTimeout=15)
    sdk_ensure_pool_functional(looper, other_nodes, sdk_wallet_client, sdk_pool_handle)
    ensure_all_nodes_have_same_data(looper, other_nodes)
