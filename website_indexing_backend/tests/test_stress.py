#!/usr/bin/env python3
"""
Full-scale stress test for parallel processing.
Tests: 100+50+50 pages, PDFs, parallel execution, API responsiveness.
"""

import httpx
import asyncio
import time
import psutil
import sys

API_BASE = 'http://localhost:8080'
TOKEN = 'TKhPt8qX7ZX8Q6A65E3BowcsNI2yUJZC96BXqmXqj'

async def stress_test():
    sites = [
        {'url': 'https://dbatu.ac.in/', 'name': 'DBATU', 'max_pages': 100},
        {'url': 'https://omkarthawakar.github.io/', 'name': 'Omkar', 'max_pages': 50},
        {'url': 'https://hishamcholakkal.com/', 'name': 'Hisham', 'max_pages': 50},
    ]
    
    print('=' * 75)
    print('STRESS TEST: 100+50+50 pages, PDFs, Parallel Processing')
    print('=' * 75)
    
    async with httpx.AsyncClient(timeout=120) as client:
        # Baseline check
        print('\n[BASELINE]')
        try:
            resp = await client.get(f'{API_BASE}/health')
            print(f'  API: {resp.status_code} | Memory: {psutil.virtual_memory().percent:.1f}%')
        except Exception as e:
            print(f'  ERROR: API not reachable - {e}')
            print('  Please ensure API is running on port 8080')
            return
        
        # Submit all tasks simultaneously
        print(f'\n[SUBMIT] {len(sites)} tasks at once...')
        
        async def submit(s):
            r = await client.post(
                f'{API_BASE}/index',
                json={
                    'url': s['url'], 
                    'max_pages': s['max_pages'], 
                    'external_job_id': f"stress_{s['name']}_{int(time.time())}"
                },
                headers={'Authorization': f'Bearer {TOKEN}'}
            )
            return {
                'name': s['name'], 
                'task_id': r.json().get('task_id'), 
                'max': s['max_pages'], 
                'start': time.time()
            }
        
        tasks = await asyncio.gather(*[submit(s) for s in sites])
        for t in tasks:
            print(f"  {t['name']}: {t['task_id'][:8]}... (max {t['max']} pages)")
        
        # Monitor progress
        print('\n[MONITORING] Every 15s')
        latencies, results, done = [], {}, set()
        start = time.time()
        
        while len(done) < len(tasks):
            await asyncio.sleep(15)
            elapsed = time.time() - start
            
            # Check API health
            try:
                t0 = time.time()
                await client.get(f'{API_BASE}/health', timeout=5)
                lat = (time.time() - t0) * 1000
                latencies.append(lat)
            except:
                lat = -1
                latencies.append(-1)
            
            # Check task progress
            status_parts = []
            for t in tasks:
                if t['task_id'] in done:
                    status_parts.append(f"{t['name']}: Done")
                    continue
                try:
                    r = await client.get(
                        f"{API_BASE}/tasks/{t['task_id']}",
                        headers={'Authorization': f'Bearer {TOKEN}'}, 
                        timeout=10
                    )
                    d = r.json()
                    s = d.get('status', '?')
                    p = d.get('progress', {})
                    if s in ('completed', 'failed'):
                        done.add(t['task_id'])
                        results[t['name']] = {
                            'status': s, 
                            'dur': time.time() - t['start'],
                            'urls': p.get('urls_processed', 0), 
                            'docs': p.get('documents_indexed', 0)
                        }
                        status_parts.append(f"{t['name']}: Done")
                    else:
                        status_parts.append(f"{t['name']}: {p.get('urls_processed', 0)}/{t['max']}")
                except:
                    status_parts.append(f"{t['name']}: ?")
            
            mem = psutil.virtual_memory().percent
            api_str = f'{lat:.0f}ms' if lat > 0 else 'ERR'
            print(f"  [{elapsed:>3.0f}s] API:{api_str:>6} Mem:{mem:>5.1f}% | {' | '.join(status_parts)}")
            
            if elapsed > 900:  # 15 min timeout
                print('  TIMEOUT!')
                break
        
        # Print results
        total_time = time.time() - start
        print('\n' + '=' * 75)
        print('RESULTS')
        print('=' * 75)
        
        total_pages, total_docs = 0, 0
        for n, r in results.items():
            icon = '✅' if r['status'] == 'completed' else '❌'
            print(f"  {icon} {n}: {r['status']} in {r['dur']:.0f}s | Pages:{r['urls']} Docs:{r['docs']}")
            total_pages += r['urls']
            total_docs += r['docs']
        
        print(f'\n  TOTALS: {total_pages} pages, {total_docs} docs in {total_time:.0f}s')
        
        valid_lat = [l for l in latencies if l > 0]
        if valid_lat:
            print(f'\n  API Responsiveness:')
            print(f'    Avg: {sum(valid_lat)/len(valid_lat):.0f}ms')
            print(f'    Max: {max(valid_lat):.0f}ms')
            print(f'    Blocked: {len([l for l in latencies if l < 0])} times')
        
        sum_dur = sum(r['dur'] for r in results.values())
        if total_time > 0 and len(results) > 0:
            efficiency = sum_dur / total_time / len(results)
            print(f'\n  Parallel efficiency: {efficiency:.1%}')
        
        print('\n' + '=' * 75)
        ok = all(r['status'] == 'completed' for r in results.values())
        blocked = len([l for l in latencies if l < 0])
        if ok and blocked == 0 and (not valid_lat or max(valid_lat) < 5000):
            print('VERDICT: ✅ STRESS TEST PASSED')
        else:
            print('VERDICT: ⚠️ ISSUES DETECTED')
        print('=' * 75)


if __name__ == '__main__':
    asyncio.run(stress_test())
