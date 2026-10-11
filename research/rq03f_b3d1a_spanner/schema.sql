CREATE TABLE AuthorityHead (
  HeadId STRING(64) NOT NULL,
  Sequence INT64 NOT NULL,
  StateJSONB64 STRING(MAX) NOT NULL,
  StateDigest STRING(64) NOT NULL,
  PolicyEpoch INT64 NOT NULL,
  IndexRevision INT64 NOT NULL,
  IndexSHA256 STRING(64) NOT NULL,
  IndexBytesB64 STRING(MAX) NOT NULL,
  RevocationStateSHA256 STRING(64) NOT NULL,
  FencingToken INT64 NOT NULL,
  PendingTransitionId STRING(160)
) PRIMARY KEY (HeadId);

CREATE TABLE OwnerRoleRegistry (
  AuthorizationReference STRING(256) NOT NULL,
  Principal STRING(256) NOT NULL,
  Role STRING(64) NOT NULL,
  AuthorizationClass STRING(64) NOT NULL,
  OperationPurpose STRING(64) NOT NULL,
  Epoch INT64 NOT NULL,
  ValidFrom TIMESTAMP NOT NULL,
  ValidUntil TIMESTAMP NOT NULL,
  Revoked BOOL NOT NULL,
  ApproverPrincipal STRING(256) NOT NULL
) PRIMARY KEY (AuthorizationReference);

CREATE TABLE TransitionRecords (
  TransitionId STRING(160) NOT NULL,
  Status STRING(16) NOT NULL,
  RequestJSONB64 STRING(MAX) NOT NULL,
  RequestSHA256 STRING(64) NOT NULL,
  ActorPrincipal STRING(256) NOT NULL,
  OperationPurpose STRING(64) NOT NULL,
  ApprovalReference STRING(256) NOT NULL,
  AuthorizedRole STRING(64) NOT NULL,
  AuthorizationClass STRING(64) NOT NULL,
  AuthorizationEpoch INT64 NOT NULL,
  RevocationSHA256 STRING(64) NOT NULL,
  ExpectedSequence INT64 NOT NULL,
  ExpectedStateDigest STRING(64) NOT NULL,
  ProposedStateDigest STRING(64) NOT NULL,
  ProposedIndexRevision INT64 NOT NULL,
  ProposedIndexSHA256 STRING(64) NOT NULL,
  CandidateIndexB64 STRING(MAX) NOT NULL,
  ReservationExpiresAt TIMESTAMP NOT NULL,
  FencingToken INT64 NOT NULL,
  ResolutionCode STRING(64),
  ResultSequence INT64,
  ResultStateDigest STRING(64)
) PRIMARY KEY (TransitionId);

CREATE TABLE TransitionEvents (
  TransitionId STRING(160) NOT NULL,
  EventNumber INT64 NOT NULL,
  EventType STRING(16) NOT NULL,
  EventJSONB64 STRING(MAX) NOT NULL,
  EventSHA256 STRING(64) NOT NULL,
  OccurredAt TIMESTAMP NOT NULL
) PRIMARY KEY (TransitionId, EventNumber),
  INTERLEAVE IN PARENT TransitionRecords ON DELETE CASCADE;

CREATE TABLE IndexHistory (
  IndexRevision INT64 NOT NULL,
  IndexSHA256 STRING(64) NOT NULL,
  IndexBytesB64 STRING(MAX) NOT NULL,
  TransitionId STRING(160) NOT NULL
) PRIMARY KEY (IndexRevision);
