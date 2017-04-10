import json
from typing import Tuple, List

from ledger.serializers.json_serializer import JsonSerializer
from plenum.common.exceptions import UnauthorizedClientRequest
from plenum.common.ledger import Ledger
from plenum.common.types import f
from stp_core.common.log import getlogger
from plenum.common.request import Request
from plenum.common.state import State
from plenum.common.constants import TXN_TYPE, NYM, ROLE, STEWARD, TARGET_NYM, VERKEY, \
    GUARDIAN
from plenum.common.txn_util import reqToTxn
from plenum.server.req_handler import RequestHandler

logger = getlogger()


class DomainRequestHandler(RequestHandler):

    def __init__(self, ledger, state, reqProcessors):
        super().__init__(ledger, state)
        self.reqProcessors = reqProcessors
        self.stateSerializer = JsonSerializer()

    def validate(self, req: Request, config=None):
        if req.operation.get(TXN_TYPE) == NYM:
            origin = req.identifier
            error = None
            if not self.isSteward(self.state,
                                  origin, isCommitted=False):
                error = "Only Steward is allowed to do these transactions"
            if req.operation.get(ROLE) == STEWARD:
                if self.stewardThresholdExceeded(config):
                    error = "New stewards cannot be added by other stewards " \
                            "as there are already {} stewards in the system".\
                            format(config.stewardThreshold)
            if error:
                raise UnauthorizedClientRequest(req.identifier,
                                                req.reqId,
                                                error)

    def _reqToTxn(self, req: Request):
        txn = reqToTxn(req)
        for processor in self.reqProcessors:
            res = processor.process(req)
            txn.update(res)

        return txn

    def apply(self, req: Request):
        txn = self._reqToTxn(req)
        self.ledger.appendTxns([txn])
        self.updateState([txn])
        return txn

    def updateState(self, txns, isCommitted=False):
        for txn in txns:
            typ = txn.get(TXN_TYPE)
            nym = txn.get(TARGET_NYM)
            if typ == NYM:
                self.updateNym(nym, {
                    f.IDENTIFIER.nm: txn.get(f.IDENTIFIER.nm),
                    ROLE: txn.get(ROLE),
                    VERKEY: txn.get(VERKEY)
                }, isCommitted=isCommitted)
            else:
                logger.debug('Cannot apply request of type {} to state'.format(typ))

    def countStewards(self) -> int:
        """Count the number of stewards added to the pool transaction store"""
        allTxns = self.ledger.getAllTxn().values()
        return sum(1 for txn in allTxns if (txn[TXN_TYPE] == NYM) and
                   (txn.get(ROLE) == STEWARD))

    def stewardThresholdExceeded(self, config) -> bool:
        """We allow at most `stewardThreshold` number of  stewards to be added
        by other stewards"""
        return self.countStewards() > config.stewardThreshold

    def updateNym(self, nym, data, isCommitted=True):
        existingData = self.getNymDetails(self.state, nym,
                                          isCommitted=isCommitted)
        existingData.update(data)
        key = nym.encode()
        val = self.stateSerializer.serialize(existingData)
        self.state.set(key, val)
        return existingData

    def hasNym(self, nym, isCommitted: bool = True):
        key = nym.encode()
        data = self.state.get(key, isCommitted)
        return bool(data)

    @staticmethod
    def getSteward(state, nym, isCommitted: bool = True):
        nymData = DomainRequestHandler.getNymDetails(state, nym, isCommitted)
        if not nymData:
            return {}
        else:
            if nymData.get(ROLE) == STEWARD:
                return nymData
            else:
                return {}

    @staticmethod
    def isSteward(state, nym, isCommitted: bool = True):
        return bool(DomainRequestHandler.getSteward(state,
                                                    nym,
                                                    isCommitted))

    @staticmethod
    def getNymDetails(state, nym, isCommitted: bool = True):
        key = nym.encode()
        data = state.get(key, isCommitted)
        return json.loads(data.decode()) if data else {}
