import types
from _ast import Dict, List
from collections import Sequence

import pytest

from plenum.common.messages.node_messages import Prepare, PrePrepare, Commit
from plenum.server.node import Node
from plenum.test.delayers import icDelay, cDelay
from plenum.test.helper import waitForViewChange, sdk_send_random_and_check, \
    sdk_send_random_requests, sdk_get_replies
from plenum.test.node_request.helper import sdk_ensure_pool_functional
from plenum.test.node_catchup.helper import ensure_all_nodes_have_same_data
from plenum.test.spy_helpers import get_count
from plenum.test.stasher import delay_rules
from plenum.test.test_node import ensureElectionsDone
from stp_core.loop.eventually import eventually
from stp_core.loop.exceptions import EventuallyTimeoutException
fast_node = "Gamma"


def test_view_change_with_different_prepared_certificate(txnPoolNodeSet, looper,
                                                         sdk_pool_handle,
                                                         sdk_wallet_client,
                                                         tconf,
                                                         viewNo,
                                                         monkeypatch):

    # 1. Send some txns
    sdk_send_random_and_check(looper, txnPoolNodeSet, sdk_pool_handle,
                              sdk_wallet_client, 4)

    def start_view_change(commit: Commit):
        # if get_count(replica, replica._request_three_phase_msg) > 1:
        for node in txnPoolNodeSet:
            key = (commit.viewNo, commit.ppSeqNo)
            node.view_changer.startViewChange(
                replica.node.viewNo + 1)
            monkeypatch.delattr(node.replicas[0], "canOrder")
        return False, ""

    for node in txnPoolNodeSet:
        replica = node.replicas[0]
        monkeypatch.setattr(replica, 'canOrder', start_view_change)

    requests = sdk_send_random_requests(looper, sdk_pool_handle,
                                        sdk_wallet_client, 2)
    sdk_get_replies(looper, requests)


def tmp(prepare: Prepare, sender: str):
    print("test")


def test_view_change_in_different_time(txnPoolNodeSet, looper,
                                       sdk_pool_handle,
                                       sdk_wallet_client,
                                       tconf,
                                       monkeypatch):
    """Test case:
    given 4 nodes
    disable normal view change to make tests deterministic
    indefinitely delay receiving commit messages on all nodes
    send some requests
    wait until all nodes have same last prepare certificate
    trigger view change on all nodes (using view_changer.on_master_degradation)
    stop delaying commits on two nodes
    wait until view change is complete
    stop delaying commits on two other nodes
    try ordering transactions
    Expected result with correct view change: transactions should be ordered normally
    Expected result with current view change: transactions won't be ordered because pool is in inconsistent state
    """

    first_two_nodes = txnPoolNodeSet[:2]
    other_two_nodes = txnPoolNodeSet[2:]
    first_two_nodes_stashers = [n.nodeIbStasher for n in first_two_nodes]
    other_two_nodes_stashers = [n.nodeIbStasher for n in other_two_nodes]

    with delay_rules(first_two_nodes_stashers, cDelay()):
        with delay_rules(other_two_nodes_stashers, cDelay()):
            requests = sdk_send_random_requests(looper, sdk_pool_handle,
                                                sdk_wallet_client, 1)

            def prepare_certificate(nodes: [Node]):
                for node in nodes:
                    replica = node.replicas[0]
                    (last_pp_view_no, last_pp_seq_no) = replica.last_ordered_3pc
                    tmp = replica.last_prepared_certificate_in_view()
                    assert tmp == (replica.viewNo, last_pp_seq_no + 1)

            def view_change_done(nodes: [Node]):
                            for node in nodes:
                                assert node.viewNo == 1

            looper.run(eventually(prepare_certificate, txnPoolNodeSet,
                       retryWait=1, timeout=100))

            for node in txnPoolNodeSet:
                node.view_changer.on_master_degradation()

            # Wait for view change done on other two nodes
            looper.run(eventually(view_change_done, other_two_nodes,
                                  retryWait=1, timeout=100))

 #           ensureElectionsDone(looper=looper, nodes=txnPoolNodeSet)

        # Wait for view change done one first two nodes
        looper.run(eventually(view_change_done, first_two_nodes,
                              retryWait=1, timeout=100))

#        ensureElectionsDone(looper=looper, nodes=txnPoolNodeSet)

    sdk_get_replies(looper, requests)

    # Send requests, we should fail here :)
    sdk_send_random_and_check(looper, txnPoolNodeSet, sdk_pool_handle,
                              sdk_wallet_client, 4)


def test_delay_commits(txnPoolNodeSet, looper,
                                       sdk_pool_handle,
                                       sdk_wallet_client,
                                       tconf,
                                       monkeypatch):
    sdk_send_random_and_check(looper, txnPoolNodeSet, sdk_pool_handle,
                              sdk_wallet_client, 4)

    view_no = 1
    delay = 3
    for node in txnPoolNodeSet:
        node.nodeIbStasher.delay(cDelay(delay))

    requests = sdk_send_random_requests(looper, sdk_pool_handle,
                                        sdk_wallet_client, 2)
    for node in txnPoolNodeSet[0:2]:
        node.view_changer.sendInstanceChange(view_no)

    sdk_get_replies(looper, requests)
