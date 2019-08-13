# ReplicaValidationResult
from plenum.common import stashing_router

PROCESS = stashing_router.PROCESS
DISCARD = stashing_router.DISCARD
STASH_VIEW = 2
STASH_WATERMARKS = 3
STASH_CATCH_UP = 4
STASH_WAITING_NEW_VIEW  = 5

# ReplicaValidationReasons
INCORRECT_INSTANCE = "Incorrect instance"
INCORRECT_PP_SEQ_NO = "pp_seq_no must start from 1"
OUTSIDE_WATERMARKS = "Outside watermwarks"
FUTURE_VIEW = "Future view"
OLD_VIEW = "Old view"
CATCHING_UP = "Catching-up"
GREATER_PREP_CERT = "Greater than last prepared certificate"
ALREADY_ORDERED = "Already ordered"
ALREADY_STABLE = "Already stable checkpoint"
