from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import io
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from fastapi.testclient import TestClient

from sports_briefing.api import create_app
from sports_briefing.cli import main
from sports_briefing.golf.sportradar import (
    SCOTTIE_ID, NormalizationError, Response, discovery_order, field_contains,
    ProviderError, normalize_bundle, normalize_schedule, retrieve_scottie, schedule_url,
)
from sports_briefing.golf.storage import (
    initialize_golf_database, inspect_golf_state, load_golf_state,
    persist_golf_fetch,
)
from sports_briefing.golf.timeline import derive_golf_candidates
from sports_briefing.nfl.sportradar import TEXANS_ID
from sports_briefing.storage import StorageError
from sports_briefing.timeline import TimelineCandidate, TimelineTier, build_home_timeline, rank_candidates

FIXTURES=Path(__file__).parent/'fixtures'/'golf'
TOUR='11a4e5d0-7c21-4f3a-9b10-5e0000000001'
HARBOR='22b0a4b0-3d42-4e6b-8c20-5e0000000002'


def response(name: str, generated: str | None = None) -> Response:
    payload=json.loads((FIXTURES/f'{name}.json').read_text())
    headers=json.loads((FIXTURES/f'{name}-headers.json').read_text())
    raw=generated or headers['x-generated-date']
    when=parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat().replace('+00:00','Z') if raw else None
    return Response(f'https://api.sportradar.com/golf/trial/pga/v3/en/2026/{name}.json',payload,json.dumps(payload),raw,when,headers['Last-Modified'],headers['ETag'])


def sample():
    responses={name:response(name) for name in ('schedule','summary','leaderboard','tees','scores')}
    tournament=next(t for t in normalize_schedule(responses['schedule']) if t['id']==TOUR)
    return normalize_bundle(tournament,responses),responses


class SyntheticFixtureGuardTests(unittest.TestCase):
    """Checked-in provider fixtures are authored, not captured (see AGENTS.md)."""

    def test_golf_fixture_identities_are_synthetic(self):
        uuid=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
        for path in sorted(FIXTURES.glob('*.json')):
            text=path.read_text()
            with self.subTest(path.name):
                self.assertEqual({u for u in uuid.findall(text) if u!=SCOTTIE_ID and '5e00000' not in u}, set())
                if path.name.endswith('-headers.json'):
                    etag=json.loads(text).get('ETag')
                    self.assertTrue(etag is None or etag.strip('"').startswith('synthetic-'), etag)
                for name in re.findall(r'"name": "([^"]+)"', text):
                    self.assertTrue(name.startswith('Synthetic ') or name in {'PGA Tour', 'Scottie Scheffler', 'Scheffler, Scottie', 'Rowan Example', 'Avery Sample'}, name)

    def test_texans_live_shape_ids_are_synthetic(self):
        payload=json.loads((FIXTURES.parent/'texans_schedule_live_shape.json').read_text())
        ids=[payload['season']['id']]+[w['id'] for w in payload['weeks']]
        for week in payload['weeks']:
            for game in week['games']:
                ids+=[game['id'], game['home']['id'], game['away']['id']]
        self.assertEqual([i for i in ids if not i.startswith('synthetic-') and i!=TEXANS_ID], [])


class GolfNormalizationTests(unittest.TestCase):
    def test_identity_field_round_and_result(self):
        profile=json.loads((FIXTURES/'profile.json').read_text())
        self.assertEqual((profile['id'],profile['name']),(SCOTTIE_ID,'Scheffler, Scottie'))
        bundle,_=sample()
        t,e,rounds=bundle['tournament'],bundle['entry'],bundle['rounds']
        self.assertEqual((t['start_date'],t['course_timezone'],t['status']),('2026-08-13','America/Chicago','closed'))
        self.assertEqual((e['player_id'],e['display_name'],e['position'],e['tied'],e['score'],e['strokes']),(SCOTTIE_ID,'Scottie Scheffler',2,True,-11,273))
        self.assertIsNone(e['status']) # Missing does not mean actively playing.
        self.assertEqual(len(rounds),4)
        self.assertEqual((rounds[-1]['round_id'],rounds[-1]['number'],rounds[-1]['status'],rounds[-1]['tee_time'],rounds[-1]['score'],rounds[-1]['thru']),('5e000000-0000-4000-8000-000000000b04',4,'closed','2026-08-16T18:10:00Z',-2,18))
        self.assertIsNone(rounds[0]['tee_time'])
        self.assertEqual(rounds[-1]['updated_at'],'2026-08-16T22:31:00Z')
        wd=next(p for p in response('leaderboard').payload['leaderboard'] if p.get('status')=='WD')
        self.assertEqual((wd['status'],wd['thru'] if 'thru' in wd else wd['rounds'][0]['thru']),('WD',7))
        self.assertEqual(response('leaderboard').payload,response('leaderboard-repeat').payload)

    def test_schedule_presence_does_not_confirm_scottie(self):
        summary=response('summary')
        summary.payload['field']=[]
        self.assertFalse(field_contains(summary,TOUR))
        ordered=discovery_order(normalize_schedule(response('schedule')),date(2026,9,2))
        self.assertEqual(ordered[0]['name'],'Synthetic Harbor Open')
        self.assertNotIn('Synthetic Nations Cup',[x['name'] for x in ordered])

    def test_pre_field_upcoming_summary_is_unknown_and_skipped(self):
        pre_field=response('upcoming-pre-field')
        self.assertIsNone(pre_field.generated_at)
        self.assertNotIn('field',pre_field.payload)
        self.assertNotIn('rounds',pre_field.payload)
        self.assertNotIn('status',pre_field.payload)
        self.assertFalse(field_contains(pre_field,pre_field.payload['id']))
        bundle,responses=sample()
        schedule=deepcopy(responses['schedule'])
        schedule.payload['tournaments'].append({'id':pre_field.payload['id'],'name':pre_field.payload['name'],'event_type':'stroke','start_date':pre_field.payload['start_date'],'end_date':pre_field.payload['end_date'],'course_timezone':pre_field.payload['course_timezone'],'status':'scheduled'})
        calls=[]
        def transport(url,key,timeout):
            calls.append(url)
            if url.endswith('/schedule.json'): return schedule
            if pre_field.payload['id'] in url: return pre_field
            if f'/{HARBOR}/' in url:
                empty=deepcopy(responses['summary']); empty.payload['id']=HARBOR; empty.payload['field']=[]; return empty
            for name in ('summary','leaderboard','tees','scores'):
                suffix={'summary':'summary','leaderboard':'leaderboard','tees':'teetimes','scores':'scores'}[name]
                if url.endswith('/'+suffix+'.json'): return responses[name]
            raise AssertionError(url)
        selected,_=retrieve_scottie('private',year=2026,today=date(2026,9,2),transport=transport)
        self.assertEqual(selected['tournament']['id'],TOUR)
        self.assertTrue(any(pre_field.payload['id'] in url for url in calls))

    def test_missing_field_does_not_become_withdrawal(self):
        bundle,responses=sample()
        responses['summary'].payload['field']=[]
        with self.assertRaisesRegex(NormalizationError,'confirmed field'):
            normalize_bundle(bundle['tournament'],responses)

    def test_malformed_scope_and_score_conflict_fail(self):
        bundle,responses=sample()
        responses['scores'].payload['round']['players'][0]['score']=-3
        with self.assertRaisesRegex(NormalizationError,'conflicts'):
            normalize_bundle(bundle['tournament'],responses)
        bundle,responses=sample()
        responses['tees'].payload['round']['id']='wrong'
        with self.assertRaisesRegex(NormalizationError,'round identity'):
            normalize_bundle(bundle['tournament'],responses)

    def test_no_rounds_or_invalid_date_fails_clearly(self):
        bundle,responses=sample()
        responses['summary'].payload['rounds']=[]
        with self.assertRaisesRegex(NormalizationError,'no rounds'):
            normalize_bundle(bundle['tournament'],responses)
        bad=response('schedule'); bad.payload['tournaments'][0]['start_date']='2026-08-27T00:00:00Z'
        with self.assertRaisesRegex(NormalizationError,'date without time'):
            normalize_schedule(bad)

    def test_bounded_retrieval_confirms_field_before_other_endpoints(self):
        bundle,responses=sample()
        calls=[]
        def transport(url,key,timeout):
            calls.append(url)
            if url.endswith('/schedule.json'): return responses['schedule']
            if f'/{HARBOR}/' in url:
                empty=deepcopy(responses['summary']); empty.payload['id']=HARBOR; empty.payload['field']=[]; return empty
            if f'/{TOUR}/' in url and url.endswith('/summary.json'): return responses['summary']
            if url.endswith('/leaderboard.json'): return responses['leaderboard']
            if url.endswith('/teetimes.json'): return responses['tees']
            if url.endswith('/scores.json'): return responses['scores']
            raise AssertionError(url)
        selected,_=retrieve_scottie('private',year=2026,today=date(2026,9,2),transport=transport)
        self.assertEqual(selected['tournament']['id'],TOUR)
        self.assertEqual(len(calls),6)
        self.assertEqual(calls[0],schedule_url(2026))
        self.assertTrue(calls[1].endswith(f'/{HARBOR}/summary.json'))


class GolfStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'golf.sqlite3'
        initialize_golf_database(self.db)
        self.bundle,self.responses=sample()
        self.first='2026-09-23T05:50:00Z'

    def tearDown(self): self.tmp.cleanup()

    def save(self,bundle=None,responses=None,when=None):
        return persist_golf_fetch(self.db,bundle or self.bundle,responses or self.responses,started_at=when or self.first,completed_at=when or self.first)

    def revised(self, payload_change, keys):
        responses=deepcopy(self.responses)
        payload_change(responses)
        newer='Thu, 24 Sep 2026 00:00:00 GMT'
        for key in keys:
            r=responses[key]
            responses[key]=Response(r.url,r.payload,json.dumps(r.payload),newer,'2026-09-24T00:00:00Z',r.last_modified,r.etag)
        tournament=next(t for t in normalize_schedule(responses['schedule']) if t['id']==TOUR)
        return normalize_bundle(tournament,responses),responses

    def counts(self):
        with sqlite3.connect(self.db) as conn:
            return {table:conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('golf_tournaments','golf_entries','golf_player_rounds','golf_sources','golf_fetches')}

    def test_first_insert_rerun_and_restart(self):
        self.assertEqual(self.save()['inserted'],6)
        before=self.counts()
        self.assertEqual(before,{'golf_tournaments':1,'golf_entries':1,'golf_player_rounds':4,'golf_sources':5,'golf_fetches':1})
        times=load_golf_state(self.db)[0][0]
        second=self.save(when='2026-09-23T06:00:00Z')
        self.assertEqual((second['inserted'],second['updated'],second['no_change']),(0,0,6))
        after=self.counts(); self.assertEqual({k:v for k,v in after.items() if k!='golf_fetches'},{k:v for k,v in before.items() if k!='golf_fetches'})
        current=load_golf_state(self.db)[0][0]
        self.assertEqual(current['last_changed_at'],times['last_changed_at'])
        self.assertEqual(current['entry']['last_changed_at'],times['entry']['last_changed_at'])
        self.assertEqual(current['rounds'],times['rounds'])
        self.assertEqual(current['entry']['player_id'],SCOTTIE_ID)
        self.assertEqual(inspect_golf_state(self.db)['latest_fetch']['outcome'],'success')

    def test_newer_changed_content_updates_only_target(self):
        self.save()
        old=load_golf_state(self.db)[0][0]
        def change(responses):
            player=next(x for x in responses['leaderboard'].payload['leaderboard'] if x['id']==SCOTTIE_ID)
            player.update(score=-10,position=4,strokes=274)
            player['rounds'][-1].update(score=-1,strokes=70)
            score=responses['scores'].payload['round']['players'][0]
            score.update(score=-1,strokes=70)
        changed,responses=self.revised(change,('leaderboard','scores'))
        changed_count=self.save(changed,responses,'2026-09-23T06:05:00Z')
        self.assertEqual(changed_count['updated'],2)
        self.assertEqual(changed_count['sources_accepted'],2)
        now=load_golf_state(self.db)[0][0]
        self.assertEqual(now['entry']['score'],-10)
        self.assertEqual(now['rounds'][-1]['score'],-1)
        self.assertEqual(now['last_changed_at'],old['last_changed_at'])

    def test_older_or_equal_conflict_is_atomic(self):
        self.save()
        original=self.counts()
        def change(responses):
            next(p for p in responses['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)['position']=6
        changed,responses=self.revised(change,())
        with self.assertRaisesRegex(StorageError,'equal generation'):
            self.save(changed,responses,'2026-09-23T06:05:00Z')
        self.assertEqual(self.counts(),original)
        older=deepcopy(self.responses)
        source=older['leaderboard']; older['leaderboard']=Response(source.url,source.payload,source.body,'Sat, 15 Aug 2026 00:00:00 GMT','2026-08-15T00:00:00Z',source.last_modified,source.etag)
        with self.assertRaisesRegex(StorageError,'older'):
            self.save(responses=older)
        self.assertEqual(self.counts(),original)

    def test_selected_source_without_generation_cannot_be_accepted(self):
        no_clock=deepcopy(self.responses)
        r=no_clock['summary']
        no_clock['summary']=Response(r.url,r.payload,r.body,None,None,r.last_modified,r.etag)
        with self.assertRaisesRegex(StorageError,'lacks x-generated-date'):
            self.save(responses=no_clock)
        self.assertEqual(self.counts(),{'golf_tournaments':0,'golf_entries':0,'golf_player_rounds':0,'golf_sources':0,'golf_fetches':0})

    def test_newer_identical_generation_high_water_without_domain_churn(self):
        self.save()
        older=load_golf_state(self.db)[0][0]
        newer=deepcopy(self.responses)
        source=newer['leaderboard']; newer['leaderboard']=Response(source.url,source.payload,source.body,'Mon, 17 Aug 2026 23:40:00 GMT','2026-08-17T23:40:00Z','Wed, 23 Sep 2026 12:00:00 GMT','z')
        self.save(responses=newer,when='2026-09-23T06:05:00Z')
        self.assertEqual(load_golf_state(self.db)[0][0]['entry']['last_changed_at'],older['entry']['last_changed_at'])
        with sqlite3.connect(self.db) as conn:
            row=conn.execute("SELECT generated_at,last_modified,etag,accepted_at FROM golf_sources WHERE endpoint_key=?",(f'leaderboard:{TOUR}',)).fetchone()
        self.assertEqual(row[0],'2026-08-17T23:40:00Z')
        self.assertEqual(row[3],self.first)

    def test_scorecard_only_update_does_not_change_leaderboard_revision(self):
        self.save()
        def change(responses):
            responses['scores'].payload['round']['players'][0]['updated_at']='2026-08-16T22:32:00+00:00'
        bundle,responses=self.revised(change,('scores',))
        result=self.save(bundle,responses,'2026-09-23T06:05:00Z')
        self.assertEqual((result['updated'],result['sources_accepted'],result['sources_no_change']),(1,1,4))
        with sqlite3.connect(self.db) as conn:
            board=conn.execute("SELECT accepted_at FROM golf_sources WHERE endpoint_key=?",(f'leaderboard:{TOUR}',)).fetchone()[0]
            card=conn.execute("SELECT accepted_at FROM golf_sources WHERE endpoint_key=?",(f'scores:{TOUR}:4',)).fetchone()[0]
        self.assertEqual(board,self.first)
        self.assertEqual(card,'2026-09-23T06:05:00Z')

    def test_scorecard_only_score_change_keeps_leaderboard_hash(self):
        # Synthetic partial leaderboard: round 4 score exists only in scorecard.
        first_responses=deepcopy(self.responses)
        player=next(p for p in first_responses['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player['rounds']=player['rounds'][:3]
        tournament=next(t for t in normalize_schedule(first_responses['schedule']) if t['id']==TOUR)
        first_bundle=normalize_bundle(tournament,first_responses)
        self.save(first_bundle,first_responses)
        original_hash=first_bundle['source_semantics']['leaderboard']
        def change(responses):
            player=next(p for p in responses['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
            player['rounds']=player['rounds'][:3]
            responses['scores'].payload['round']['players'][0].update(score=-1,strokes=70)
        changed,responses=self.revised(change,('scores',))
        self.assertEqual(changed['source_semantics']['leaderboard'],original_hash)
        result=self.save(changed,responses,'2026-09-23T06:05:00Z')
        self.assertEqual((result['sources_accepted'],result['sources_no_change'],result['updated']),(1,4,1))
        self.assertEqual(load_golf_state(self.db)[0][0]['rounds'][-1]['score'],-1)

    def test_summary_end_date_conflict_detected_from_own_payload(self):
        self.save(); before=self.counts()
        def change(responses):
            for key in ('schedule','summary','leaderboard'):
                root=responses[key].payload
                if key=='schedule':
                    next(t for t in root['tournaments'] if t['id']==TOUR)['end_date']='2026-08-17'
                else: root['end_date']='2026-08-17'
        bundle,responses=self.revised(change,('schedule','leaderboard'))
        with self.assertRaisesRegex(StorageError,'equal generation.*summary'):
            self.save(bundle,responses,'2026-09-23T06:05:00Z')
        self.assertEqual(self.counts(),before)
        self.assertEqual(load_golf_state(self.db)[0][0]['end_date'],'2026-08-16')

    def test_newer_round_list_cannot_leave_stale_scheduled_round(self):
        self.save(); before=self.counts()
        def change(responses):
            responses['summary'].payload['rounds']=responses['summary'].payload['rounds'][:3]
            responses['leaderboard'].payload['rounds']=responses['leaderboard'].payload['rounds'][:3]
            player=next(p for p in responses['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
            player['rounds']=player['rounds'][:3]
            r3=responses['summary'].payload['rounds'][-1]
            for key in ('tees','scores'):
                responses[key].payload['round'].update(id=r3['id'],number=3,status=r3['status'])
            responses['tees'].payload['round']['courses'][0]['pairings'][0]['tee_time']='2026-08-15T18:00:00+00:00'
            responses['scores'].payload['round']['players'][0].update(score=-3,strokes=68,thru=18)
        bundle,responses=self.revised(change,('summary','leaderboard','tees','scores'))
        with self.assertRaisesRegex(StorageError,'omits a previously accepted round'):
            self.save(bundle,responses,'2026-09-23T06:05:00Z')
        self.assertEqual(self.counts(),before)
        self.assertEqual(len(load_golf_state(self.db)[0][0]['rounds']),4)

    def test_etag_last_modified_do_not_order_sports_state(self):
        self.save()
        changed=deepcopy(self.responses)
        source=changed['leaderboard']; changed['leaderboard']=Response(source.url,source.payload,source.body,source.generated_raw,source.generated_at,'Thu, 24 Sep 2026 00:00:00 GMT','later-etag')
        result=self.save(responses=changed,when='2026-09-23T06:05:00Z')
        self.assertEqual(result['updated'],0)

    def test_transaction_failure_rolls_back(self):
        self.save(); original=self.counts()
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TRIGGER fail_golf_round BEFORE UPDATE ON golf_player_rounds BEGIN SELECT RAISE(ABORT,'forced failure'); END")
        def change(responses):
            responses['tees'].payload['round']['courses'][0]['pairings'][0]['tee_time']='2026-08-16T18:11:00+00:00'
        changed,responses=self.revised(change,('tees',))
        with self.assertRaisesRegex(sqlite3.DatabaseError,'forced failure'):
            self.save(changed,responses,'2026-09-23T06:05:00Z')
        self.assertEqual(self.counts(),original)
        self.assertEqual(load_golf_state(self.db)[0][0]['rounds'][-1]['tee_time'],'2026-08-16T18:10:00Z')

    def test_bounded_source_retention(self):
        oversized=deepcopy(self.responses)
        r=oversized['schedule']
        oversized['schedule']=Response(r.url,r.payload,'{"diagnostic":"'+'x'*(300*1024)+'"}',r.generated_raw,r.generated_at,r.last_modified,r.etag)
        self.save(responses=oversized)
        with sqlite3.connect(self.db) as conn:
            size,truncated=conn.execute("SELECT LENGTH(raw_response),raw_truncated FROM golf_sources WHERE endpoint_key=?",(f'schedule:2026:{TOUR}',)).fetchone()
        self.assertLessEqual(size,256*1024)
        self.assertEqual(truncated,1)
        for n in range(25): self.save(when=f'2026-09-23T06:{n:02}:00Z')
        self.assertEqual(self.counts()['golf_fetches'],20)

    def test_provider_failure_does_not_touch_accepted_state(self):
        self.save()
        before=self.counts()
        with patch.dict('os.environ',{'SPORTRADAR_API_KEY':'test'},clear=False), patch('sports_briefing.cli.retrieve_scottie',side_effect=ProviderError('simulated timeout')):
            self.assertEqual(main(['ingest','scheffler','--db',str(self.db)]),1)
        self.assertEqual(self.counts(),before)


class GolfTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'timeline.sqlite3'
        initialize_golf_database(self.db)
        self.bundle,self.responses=sample()
        persist_golf_fetch(self.db,self.bundle,self.responses,started_at='2026-09-23T05:50:00Z',completed_at='2026-09-23T05:50:00Z')

    def tearDown(self): self.tmp.cleanup()

    def test_closed_result_never_fabricates_recent_candidate(self):
        self.assertEqual(build_home_timeline(self.db,as_of='2026-08-16T23:50:00Z')['items'],[])
        self.assertEqual(build_home_timeline(self.db,as_of='2026-09-23T06:00:00Z')['items'],[])

    def test_future_tee_time_imminent_routine_and_sparse(self):
        rows,_=load_golf_state(self.db)
        row=rows[0]; row['status']='scheduled'; row['entry']['position']=None; row['entry']['score']=None; row['entry']['strokes']=None
        row['rounds'][-1]['status']='scheduled'; row['rounds'][-1]['score']=None; row['rounds'][-1]['strokes']=None; row['rounds'][-1]['thru']=None
        tee=datetime(2026,9,26,12,tzinfo=timezone.utc)
        row['rounds'][-1]['tee_time']=tee.isoformat().replace('+00:00','Z')
        routine=derive_golf_candidates(rows,as_of=tee-timedelta(days=3),hide_results=True)
        imminent=derive_golf_candidates(rows,as_of=tee-timedelta(hours=3),hide_results=True)
        self.assertEqual((routine[0].tier,imminent[0].tier),(TimelineTier.ROUTINE,TimelineTier.IMMINENT))
        self.assertEqual(derive_golf_candidates(rows,as_of=tee+timedelta(minutes=1),hide_results=True),[])
        self.assertEqual(derive_golf_candidates(rows,as_of=tee-timedelta(days=8),hide_results=True),[])
        self.assertEqual(imminent[0].source_record_id,row['rounds'][-1]['round_id'])
        self.assertIsNone(imminent[0].result)
        self.assertNotIn('-11',json.dumps(imminent[0].__dict__))

    def test_missing_status_does_not_mean_playing_or_pre_round(self):
        rows,_=load_golf_state(self.db)
        rows[0]['status']='scheduled'; rows[0]['rounds'][-1]['status']=None
        self.assertEqual(derive_golf_candidates(rows,as_of=datetime(2026,8,16,12,tzinfo=timezone.utc),hide_results=False),[])

    def test_persisted_nonzero_round_score_suppresses_future_tee_candidate(self):
        # Synthetic partial play: direct score evidence exists even though
        # thru/strokes have not populated in the provider response yet.
        responses={key:deepcopy(value) for key,value in self.responses.items()}
        for key in ('schedule','summary','leaderboard'):
            root=responses[key].payload
            target=next(t for t in root['tournaments'] if t['id']==TOUR) if key=='schedule' else root
            target.update(start_date='2026-09-25',end_date='2026-09-27',status='scheduled')
        for key in ('summary','leaderboard'):
            responses[key].payload['rounds'][-1]['status']='scheduled'
        responses['tees'].payload['round']['status']='scheduled'
        responses['scores'].payload['round']['status']='scheduled'
        responses['tees'].payload['round']['courses'][0]['pairings'][0]['tee_time']='2026-09-26T12:00:00+00:00'
        board_player=next(p for p in responses['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        board_player['rounds'][-1].update(score=-1,strokes=None,thru=None)
        responses['scores'].payload['round']['players'][0].update(score=-1,strokes=None,thru=None)
        tournament=next(t for t in normalize_schedule(responses['schedule']) if t['id']==TOUR)
        bundle=normalize_bundle(tournament,responses)
        database=Path(self.tmp.name)/'synthetic-playing.sqlite3'
        initialize_golf_database(database)
        persist_golf_fetch(database,bundle,responses,started_at='2026-09-26T09:00:00Z',completed_at='2026-09-26T09:00:00Z')
        row=load_golf_state(database)[0][0]['rounds'][-1]
        self.assertEqual((row['tee_time'],row['score'],row['strokes'],row['thru']),('2026-09-26T12:00:00Z',-1,None,None))
        timeline=build_home_timeline(database,as_of='2026-09-26T09:00:00Z')
        self.assertFalse(any(item['entity']['id']=='scheffler' for item in timeline['items']))

    def test_spoiler_hidden_cli_and_http_do_not_leak_result(self):
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(['timeline','--db',str(self.db),'--as-of','2026-09-23T06:00:00Z']),0)
        body=stdout.getvalue()
        self.assertNotIn('273',body)
        self.assertNotIn('win',body.lower())
        self.assertNotIn('-11',body)
        self.assertEqual(json.loads(body)['items'],[])
        reply=TestClient(create_app(self.db)).get('/timeline?as_of=2026-09-23T06:00:00Z')
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.json()['items'],[])
        self.assertNotIn('273',reply.text)
        self.assertNotIn('win',reply.text.lower())
        revealed=TestClient(create_app(self.db)).get('/timeline?as_of=2026-09-23T06:00:00Z&hide_results=false')
        self.assertEqual(revealed.status_code,200)
        self.assertEqual(revealed.json()['items'],[])

    def test_persisted_future_tee_is_ranked_through_cli_http_boundary(self):
        # Synthetic scheduled state: the base fixtures cover a completed event.
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE golf_tournaments SET status='scheduled' WHERE tournament_id=?",(TOUR,))
            conn.execute("UPDATE golf_entries SET position=NULL,tied=NULL,score=NULL,strokes=NULL,status=NULL WHERE tournament_id=?",(TOUR,))
            conn.execute("UPDATE golf_player_rounds SET status='scheduled',tee_time='2026-09-26T12:00:00Z',score=NULL,strokes=NULL,thru=NULL WHERE number=4")
        result=build_home_timeline(self.db,as_of='2026-09-26T09:00:00Z')
        golf=[x for x in result['items'] if x['entity']['id']=='scheffler']
        self.assertEqual(len(golf),1)
        self.assertEqual((golf[0]['tier'],golf[0]['reason'],golf[0]['event_time']),('imminent','starts_soon','2026-09-26T12:00:00Z'))
        self.assertNotIn('result',golf[0])
        reply=TestClient(create_app(self.db)).get('/timeline?as_of=2026-09-26T09:00:00Z')
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.json()['items'][0]['id'],golf[0]['id'])
        self.assertEqual(reply.json()['items'][0]['reason'],golf[0]['reason'])


class GolfResultObservationTests(unittest.TestCase):
    """Synthetic state transitions; no active or transitioning Scottie snapshot was observed live."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'results.sqlite3'
        initialize_golf_database(self.db)
        self.final_bundle,self.final_responses=sample()
        self.nonterminal_responses=deepcopy(self.final_responses)
        for key in ('schedule','summary','leaderboard'):
            root=self.nonterminal_responses[key].payload
            target=next(t for t in root['tournaments'] if t['id']==TOUR) if key=='schedule' else root
            target['status']='inprogress'
        for key in ('summary','leaderboard'):
            self.nonterminal_responses[key].payload['rounds'][-1]['status']='inprogress'
        for key in ('tees','scores'):
            self.nonterminal_responses[key].payload['round']['status']='inprogress'
        player=next(p for p in self.nonterminal_responses['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player['rounds'][-1].update(score=-1,strokes=35,thru=9)
        self.nonterminal_responses['scores'].payload['round']['players'][0].update(score=-1,strokes=35,thru=9)
        for key,r in tuple(self.nonterminal_responses.items()):
            self.nonterminal_responses[key]=Response(r.url,r.payload,json.dumps(r.payload),'Sun, 16 Aug 2026 21:00:00 GMT','2026-08-16T21:00:00Z',r.last_modified,r.etag)
        tournament=next(t for t in normalize_schedule(self.nonterminal_responses['schedule']) if t['id']==TOUR)
        self.nonterminal_bundle=normalize_bundle(tournament,self.nonterminal_responses)

    def tearDown(self): self.tmp.cleanup()

    def ingest(self,bundle,responses,at):
        return persist_golf_fetch(self.db,bundle,responses,started_at=at,completed_at=at)

    def entry(self):
        return load_golf_state(self.db)[0][0]['entry']

    def transition(self):
        self.ingest(self.nonterminal_bundle,self.nonterminal_responses,'2026-08-16T21:30:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])
        self.ingest(self.final_bundle,self.final_responses,'2026-08-17T00:00:00Z')
        self.assertEqual(self.entry()['result_finalized_observed_at'],'2026-08-17T00:00:00Z')

    def test_known_transition_is_sticky_on_rerun_restart_and_correction(self):
        self.transition()
        before=self.entry()
        rerun=self.ingest(self.final_bundle,self.final_responses,'2026-08-17T01:00:00Z')
        self.assertEqual((rerun['inserted'],rerun['updated'],rerun['no_change']),(0,0,6))
        self.assertEqual(self.entry()['last_changed_at'],before['last_changed_at'])
        changed=deepcopy(self.final_responses)
        player=next(p for p in changed['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player.update(position=4,score=-10,strokes=274)
        player['rounds'][-1].update(score=-1,strokes=70)
        changed['scores'].payload['round']['players'][0].update(score=-1,strokes=70)
        for key in ('leaderboard','scores'):
            r=changed[key]
            changed[key]=Response(r.url,r.payload,json.dumps(r.payload),'Mon, 17 Aug 2026 01:30:00 GMT','2026-08-17T01:30:00Z',r.last_modified,'changed-etag')
        tournament=next(t for t in normalize_schedule(changed['schedule']) if t['id']==TOUR)
        corrected=normalize_bundle(tournament,changed)
        self.assertEqual(self.ingest(corrected,changed,'2026-08-17T02:00:00Z')['updated'],2)
        self.assertEqual(self.entry()['result_finalized_observed_at'],'2026-08-17T00:00:00Z')
        # A second process reads the durable observation, independently of this test process.
        import subprocess
        import sys
        output=subprocess.check_output([sys.executable,'-m','sports_briefing','inspect','scheffler','--db',str(self.db)],text=True)
        self.assertEqual(json.loads(output)['tournaments'][0]['entry']['result_finalized_observed_at'],'2026-08-17T00:00:00Z')

    def test_historical_first_import_and_delayed_transition_never_get_recent_time(self):
        self.ingest(self.final_bundle,self.final_responses,'2026-09-23T05:50:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])
        self.assertEqual(build_home_timeline(self.db,as_of='2026-09-23T06:00:00Z')['items'],[])
        other=Path(self.tmp.name)/'delayed.sqlite3'
        initialize_golf_database(other)
        persist_golf_fetch(other,self.nonterminal_bundle,self.nonterminal_responses,started_at='2026-09-22T00:00:00Z',completed_at='2026-09-22T00:00:00Z')
        persist_golf_fetch(other,self.final_bundle,self.final_responses,started_at='2026-09-23T00:00:00Z',completed_at='2026-09-23T00:00:00Z')
        self.assertIsNone(load_golf_state(other)[0][0]['entry']['result_finalized_observed_at'])

    def test_closed_incomplete_first_import_then_complete_correction_is_not_transition(self):
        incomplete=deepcopy(self.final_responses)
        player=next(p for p in incomplete['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player['position']=None
        tournament=next(t for t in normalize_schedule(incomplete['schedule']) if t['id']==TOUR)
        bundle=normalize_bundle(tournament,incomplete)
        self.ingest(bundle,incomplete,'2026-08-16T23:45:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])
        corrected=deepcopy(self.final_responses)
        r=corrected['leaderboard']
        corrected['leaderboard']=Response(r.url,r.payload,r.body,'Mon, 17 Aug 2026 00:10:00 GMT','2026-08-17T00:10:00Z',r.last_modified,r.etag)
        self.ingest(self.final_bundle,corrected,'2026-08-17T00:15:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])

    def test_prior_explicit_withdrawal_does_not_count_as_nonterminal_result(self):
        prior=deepcopy(self.nonterminal_responses)
        player=next(p for p in prior['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player['status']='WD'
        tournament=next(t for t in normalize_schedule(prior['schedule']) if t['id']==TOUR)
        bundle=normalize_bundle(tournament,prior)
        self.ingest(bundle,prior,'2026-08-16T21:30:00Z')
        self.ingest(self.final_bundle,self.final_responses,'2026-08-17T00:00:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])

    def test_impossible_zero_stroke_final_round_does_not_observe_result(self):
        self.ingest(self.nonterminal_bundle,self.nonterminal_responses,'2026-08-16T21:30:00Z')
        impossible=deepcopy(self.final_responses)
        player=next(p for p in impossible['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player['rounds'][-1]['strokes']=0
        impossible['scores'].payload['round']['players'][0]['strokes']=0
        tournament=next(t for t in normalize_schedule(impossible['schedule']) if t['id']==TOUR)
        bundle=normalize_bundle(tournament,impossible)
        self.ingest(bundle,impossible,'2026-08-17T00:00:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])

    def test_nonessential_final_fields_can_disappear_without_losing_clock(self):
        self.transition()
        sparse=deepcopy(self.final_responses)
        player=next(p for p in sparse['leaderboard'].payload['leaderboard'] if p['id']==SCOTTIE_ID)
        player.pop('tied')
        sparse['scores'].payload['round']['players'][0].pop('updated_at')
        for key in ('leaderboard','scores'):
            r=sparse[key]
            sparse[key]=Response(r.url,r.payload,json.dumps(r.payload),'Mon, 17 Aug 2026 01:30:00 GMT','2026-08-17T01:30:00Z',r.last_modified,r.etag)
        tournament=next(t for t in normalize_schedule(sparse['schedule']) if t['id']==TOUR)
        bundle=normalize_bundle(tournament,sparse)
        self.ingest(bundle,sparse,'2026-08-17T02:00:00Z')
        self.assertEqual(self.entry()['result_finalized_observed_at'],'2026-08-17T00:00:00Z')
        item=derive_golf_candidates(load_golf_state(self.db)[0],as_of=datetime(2026,8,17,2,tzinfo=timezone.utc),hide_results=True)[0]
        self.assertEqual(item.tier,TimelineTier.RECENT_RESULT)

    def test_invalid_local_time_guard_rejects_transition_atomically(self):
        self.ingest(self.nonterminal_bundle,self.nonterminal_responses,'2026-08-16T21:30:00Z')
        before=self.entry()
        with self.assertRaisesRegex(StorageError,'observation time'):
            self.ingest(self.final_bundle,self.final_responses,'2026-08-17T00:00:00')
        self.assertEqual(self.entry(),before)

    def test_revision_rejections_and_atomic_failure_do_not_observe(self):
        self.ingest(self.nonterminal_bundle,self.nonterminal_responses,'2026-08-16T21:30:00Z')
        equal=deepcopy(self.final_responses)
        for key,r in tuple(equal.items()):
            equal[key]=Response(r.url,r.payload,r.body,'Sun, 16 Aug 2026 21:00:00 GMT','2026-08-16T21:00:00Z',r.last_modified,r.etag)
        with self.assertRaisesRegex(StorageError,'equal generation'):
            self.ingest(self.final_bundle,equal,'2026-08-17T00:00:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])
        older=deepcopy(self.final_responses)
        r=older['leaderboard']; older['leaderboard']=Response(r.url,r.payload,r.body,'Sun, 16 Aug 2026 20:00:00 GMT','2026-08-16T20:00:00Z',r.last_modified,r.etag)
        with self.assertRaisesRegex(StorageError,'older'):
            self.ingest(self.final_bundle,older,'2026-08-17T00:00:00Z')
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TRIGGER reject_round BEFORE UPDATE ON golf_player_rounds BEGIN SELECT RAISE(ABORT,'forced failure'); END")
        with self.assertRaisesRegex(sqlite3.DatabaseError,'forced failure'):
            self.ingest(self.final_bundle,self.final_responses,'2026-08-17T00:00:00Z')
        self.assertIsNone(self.entry()['result_finalized_observed_at'])

    def test_recent_result_window_spoiler_and_existing_global_rank(self):
        self.transition()
        as_of='2026-08-17T01:00:00Z'
        hidden=build_home_timeline(self.db,as_of=as_of)
        golf=[x for x in hidden['items'] if x['entity']['id']=='scheffler']
        self.assertEqual(len(golf),1)
        self.assertEqual((golf[0]['tier'],golf[0]['event_time'],golf[0]['reason']),('recent_result','2026-08-17T00:00:00Z','recent_result'))
        self.assertTrue(golf[0]['result_hidden'])
        for forbidden in ('position','victory','win','tied','score','strokes','-11','273','winner','WD'):
            self.assertNotIn(forbidden,json.dumps(golf).lower())
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(['timeline','--db',str(self.db),'--as-of',as_of]),0)
        self.assertEqual(json.loads(stdout.getvalue())['items'],hidden['items'])
        reply=TestClient(create_app(self.db)).get('/timeline?as_of='+as_of)
        self.assertEqual(reply.status_code,200)
        self.assertEqual(reply.json()['items'][0]['id'],golf[0]['id'])
        self.assertEqual(reply.json()['items'][0]['summary'],golf[0]['summary'])
        self.assertNotIn('score',reply.text.lower())
        revealed=build_home_timeline(self.db,as_of=as_of,hide_results=False)
        self.assertIn('tied for position 2',revealed['items'][0]['summary'])
        self.assertEqual(derive_golf_candidates(load_golf_state(self.db)[0],as_of=datetime(2026,8,18,13,tzinfo=timezone.utc),hide_results=True),[])
        self.assertEqual(len(derive_golf_candidates(load_golf_state(self.db)[0],as_of=datetime(2026,8,18,12,tzinfo=timezone.utc),hide_results=True)),1)
        self.assertEqual(derive_golf_candidates(load_golf_state(self.db)[0],as_of=datetime(2026,8,16,23,tzinfo=timezone.utc),hide_results=True),[])
        routine=TimelineCandidate(
            stable_id='arsenal:synthetic:fixture',entity_id='arsenal',entity_name='Arsenal',sport='football',item_type='fixture',event_state='PRE_GAME',tier=TimelineTier.ROUTINE,
            title='Arsenal fixture',summary='Scheduled match.',event_time='2026-08-19T00:00:00Z',change_time=None,
            competition={'code':'PL','name':'Premier League'},source_provider='fixture',source_attribution='fixture',source_generated_at=as_of,source_observed_at=as_of,source_record_id='arsenal-test',
        )
        golf_candidate=derive_golf_candidates(load_golf_state(self.db)[0],as_of=datetime.fromisoformat(as_of.replace('Z','+00:00')),hide_results=True)[0]
        ranked=rank_candidates([routine,golf_candidate],as_of=datetime.fromisoformat(as_of.replace('Z','+00:00')))
        self.assertEqual([item.entity_id for item in ranked],['scheffler','arsenal'])

    def test_reopen_retains_observation_but_suppresses_candidate(self):
        self.transition()
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE golf_tournaments SET status='inprogress' WHERE tournament_id=?",(TOUR,))
        self.assertEqual(self.entry()['result_finalized_observed_at'],'2026-08-17T00:00:00Z')
        self.assertEqual(build_home_timeline(self.db,as_of='2026-08-17T01:00:00Z')['items'],[])

    def test_legacy_schema_migrates_null_without_read_only_writes(self):
        self.ingest(self.final_bundle,self.final_responses,'2026-09-23T05:50:00Z')
        with sqlite3.connect(self.db) as conn:
            conn.execute('ALTER TABLE golf_entries DROP COLUMN result_finalized_observed_at')
        before=self.db.stat().st_mtime_ns
        self.assertIsNone(load_golf_state(self.db)[0][0]['entry']['result_finalized_observed_at'])
        self.assertEqual(self.db.stat().st_mtime_ns,before)
        initialize_golf_database(self.db)
        self.assertIsNone(self.entry()['result_finalized_observed_at'])
        initialize_golf_database(self.db)
        with sqlite3.connect(self.db) as conn:
            columns=[row[1] for row in conn.execute('PRAGMA table_info(golf_entries)')]
        self.assertEqual(columns.count('result_finalized_observed_at'),1)


if __name__=='__main__': unittest.main()
