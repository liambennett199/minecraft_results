**Lesson 2**

Now we follow one round from birth to death.

The best files for this lesson are:
- [rounds/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/rounds/service.py:9)
- [submissions/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/submissions/service.py:13)
- [scoreboards/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/scoreboards/service.py:18)
- [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:87)

## 1. A Round Is Created

The first round starts in [rounds/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/rounds/service.py:14) with `bootstrap_first_round()`.

What it does:
- checks if a submission round already exists
- chooses the first round start time
- creates a new round with status `submission_open`

The actual row creation happens in `_create_submission_round()` at [rounds/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/rounds/service.py:25).

That method calculates:
- `submission_open_at`
- `evaluation_start_at`
- `scoreboard_deadline_at`
- `round_end_at`

So a round is really just a time window plus status.

## 2. Miners Submit During `submission_open`

Miners first ask the backend: “where do I upload my tarball?”

That starts at `POST /miner/submissions/slot` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:92).

The real logic is in `SubmissionService.create_submission_slot()` at [submissions/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/submissions/service.py:19).

What happens there:
- backend checks there is a current submission round
- backend checks the filename ends with `.tar.gz`
- backend creates a `submission_id`
- backend allocates a storage key like `submissions/{round}/{hotkey}/{submission_id}/...`
- backend returns a temporary upload URL

Important point: at this stage, the backend has not accepted the submission yet. It only created a slot.

## 3. Miner Uploads Bytes

The miner uploads raw bytes to `/objects/upload/{token}` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:365).

That endpoint:
- checks token exists
- checks token is not expired
- checks token was not already used
- writes the bytes to object storage
- marks the upload token as consumed

Still, the backend has only stored bytes. It has not judged whether the submission is valid.

## 4. Miner Finalizes Submission

Then the miner calls `POST /miner/submissions/finalize` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:108).

The real work is in `SubmissionService.finalize_submission()` at [submissions/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/submissions/service.py:68).

This method:
- loads the submission row
- confirms the signer hotkey owns that submission
- confirms the round is still open
- confirms the uploaded object exists
- reads the tarball bytes
- validates the archive using [submissions/checks.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/submissions/checks.py:8)
- stores `sha256`, `size_bytes`, and acceptance/rejection result

Validation rules include:
- max size limit
- valid `.tar.gz`
- no path traversal
- no symlinks/devices
- must contain root `package.json`
- must contain root `index.js`

If the miner already had an older accepted submission for the same round, `store.py` marks the old one as replaced in [api/store.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/store.py:265).

That is how “latest submission before deadline wins” is implemented.

## 5. Owner Freezes The Round

When submission time ends, the owner validator calls `POST /admin/rounds/{round_id}/freeze` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:346).

The main logic is `freeze_current_submission_round()` in [rounds/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/rounds/service.py:36).

This is the most important step in the whole backend.

Freeze does five things:
1. verifies the round is still `submission_open`
2. records `freeze_at` and `freeze_block_hash`
3. derives `round_seed_hex`
4. builds the frozen roster from accepted unreplaced submissions
5. immediately opens the next submission round

This means:
- round `N` becomes `evaluating`
- round `N+1` becomes the new `submission_open`

That overlap is intentional.

## 6. Frozen Roster Is Published To Validators

During freeze, the backend writes one roster manifest in [rounds/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/rounds/service.py:48).

The manifest contains:
- `round_id`
- `freeze_block_hash`
- `round_seed_hex`
- `mission_id`
- deadlines
- one entry per accepted miner submission

Validators fetch it from `GET /validator/rounds/{round_id}/roster` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:131).

This is the backend’s main “publish once, everyone evaluates the same thing” behavior.

## 7. Validators Upload Artifacts During Evaluation

While the round is `evaluating`, validators ask for artifact upload slots through `POST /validator/artifacts/slot` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:164).

Business logic is in `create_artifact_slot()` at [scoreboards/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/scoreboards/service.py:23).

Rules:
- round must exist
- round must still be `evaluating`
- artifact kind must be `report_json` or `recording_mcpr`

Then validators upload the files through `/objects/upload/{token}` just like miners did.

## 8. Validators Upload One Scoreboard

After artifacts are in storage, validator sends one raw scoreboard using `POST /validator/scoreboards` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:187).

The backend validates it in `validate_scoreboard()` at [scoreboards/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/scoreboards/service.py:53).

Checks include:
- scoreboard deadline not passed
- no duplicate miner rows
- all scores are finite
- referenced artifact files really exist

If valid, `store_scoreboard()` at [scoreboards/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/scoreboards/service.py:71):
- writes one scoreboard JSON object to storage
- stores one scoreboard metadata row
- links the artifact keys into `validator_artifacts`

Backend stores the raw scoreboard exactly as uploaded. It does not aggregate.

## 9. Validators Upload Consensus Result

After local averaging, validators call `POST /validator/consensus-results` in [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:233).

`store_consensus_result()` at [scoreboards/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/scoreboards/service.py:109) just stores:
- who the validator is
- which round
- who they believe the top miner is

Again, backend stores this for observability only. It is not the judge.

## 10. Round Becomes Public

Public access is controlled by `RoundService.public_round()` in [rounds/service.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/rounds/service.py:84).

Rule:
- before `round_end_at`, public endpoints return 403
- after `round_end_at`, round data is public

That logic is used by:
- `GET /public/rounds/{round_id}` at [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:243)
- `GET /public/rounds/{round_id}/roster` at [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:269)
- `GET /public/rounds/{round_id}/scoreboards` at [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:303)
- `GET /public/rounds/{round_id}/consensus-results` at [api/main.py](D:\Bittensor\MC_Subnet\neverplayalone_api\neverplayalone_backend/api/main.py:313)

## 11. The Whole Lifecycle In One Sentence

A round is:
1. opened for submissions
2. filled with the latest valid miner tarballs
3. frozen into a roster
4. evaluated by validators
5. filled with artifacts and scoreboards
6. followed by validator consensus uploads
7. made public only after end time

## 12. What To Keep In Mind

The backend’s biggest state transition is:

- `submission_open` -> `evaluating` -> `completed`

And the most important protocol guarantee is:

- once frozen, the roster for that round does not change

That is what makes validator-local evaluation possible.

If you want, Lesson 3 should be: **the database schema and what each table means**.