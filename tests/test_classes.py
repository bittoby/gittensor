import pytest

from gittensor.classes import FileChange, PullRequest


def _file_change(filename: str) -> FileChange:
    return FileChange(
        pr_number=0,
        repository_full_name='nextcloud/android',
        filename=filename,
        changes=10,
        additions=10,
        deletions=0,
        status='added',
    )


@pytest.mark.parametrize(
    'filename',
    [
        'app/src/androidTest/java/com/owncloud/android/UploadIT.java',
        'app/src/androidTest/java/com/owncloud/android/AbstractIT.java',
        'app/src/androidTest/java/com/nextcloud/client/ActivitiesFragmentIT.kt',
        'app/src/androidTestGeneric/java/com/example/FooIT.java',
        'app/src/androidTestGplay/java/com/example/BarIT.kt',
        'app/src/androidTest/java/com/example/HelperUtils.kt',
        'src/integrationTest/java/com/example/FooIT.java',
        'src/integrationTest/kotlin/com/example/HelperKt.kt',
    ],
)
def test_is_test_file_detects_gradle_test_source_sets(filename):
    assert _file_change(filename).is_test_file() is True


@pytest.mark.parametrize(
    'filename',
    [
        'src/main/java/com/example/SomeIT.java',
        'core/MyClassIT.kt',
        'lib/HttpIT.kts',
    ],
)
def test_is_test_file_detects_maven_failsafe_it_suffix(filename):
    assert _file_change(filename).is_test_file() is True


@pytest.mark.parametrize(
    'filename',
    [
        'spec/models/account_spec.rb',
        'spec/models/account_alias_spec.rb',
        'spec/requests/statuses_spec.rb',
        'spec/controllers/home_controller_spec.rb',
        'spec/support/helpers.rb',
        'spec/rails_helper.rb',
        'spec/fixtures/files/avatar.gif',
    ],
)
def test_is_test_file_detects_rspec_spec_directory(filename):
    assert _file_change(filename).is_test_file() is True


@pytest.mark.parametrize(
    'filename',
    [
        'lib/foo_spec.rb',
        'app/services/account_spec.rb',
        'some/deep/path/bar_spec.rb',
    ],
)
def test_is_test_file_detects_rspec_underscore_suffix(filename):
    assert _file_change(filename).is_test_file() is True


@pytest.mark.parametrize(
    'filename',
    [
        'app/src/main/java/com/example/Edit.java',
        'app/src/main/java/com/example/Commit.java',
        'app/src/main/java/com/example/Audit.java',
        'app/src/main/java/com/example/Visit.java',
        'app/src/main/java/com/example/Exit.java',
        'app/src/main/kotlin/com/example/Wait.kt',
        'app/src/main/kotlin/com/example/Init.kt',
        'app/src/main/kotlin/com/example/Unit.kt',
        'app/build.gradle.kts',
        'src/main/java/com/example/Bar.java',
        'src/main/java/com/example/aIT.java',
        'src/main/java/com/example/IT.java',
        'docs/androidtest.md',
        'tools/androidtestutils.py',
        'lib/specification.rb',
        'app/services/specimen.rb',
        'config/specs.yml',
        'openapi/spec.yaml',
        'docs/specs/api.md',
    ],
)
def test_is_test_file_rejects_non_test_lookalikes(filename):
    assert _file_change(filename).is_test_file() is False


def test_is_test_file_preserves_existing_test_conventions():
    assert _file_change('src/tests/test_foo.py').is_test_file() is True
    assert _file_change('src/__tests__/foo.test.js').is_test_file() is True
    assert _file_change('pkg/foo_test.go').is_test_file() is True
    assert _file_change('spec/spec_helper.rb').is_test_file() is True
    assert _file_change('src/foo/bar.py').is_test_file() is False


def test_pull_request_handles_deleted_label_event():
    pr_data = {
        'number': 42,
        'repository': {'owner': {'login': 'entrius'}, 'name': 'gittensor'},
        'state': 'OPEN',
        'closingIssuesReferences': {'nodes': []},
        'bodyText': 'Fix bug',
        'lastEditedAt': None,
        'mergedAt': None,
        'timelineItems': {'nodes': [{'label': None}]},
        'title': 'fix: guard deleted label events',
        'author': {'login': 'alice'},
        'createdAt': '2026-04-18T00:00:00Z',
        'additions': 3,
        'deletions': 1,
        'commits': {'totalCount': 1},
        'headRefOid': 'abc123',
        'baseRefOid': 'def456',
    }

    pr = PullRequest.from_graphql_response(pr_data, uid=1, hotkey='5Hotkey', github_id='123')

    assert pr.label is None
    assert pr.author_login == 'alice'
