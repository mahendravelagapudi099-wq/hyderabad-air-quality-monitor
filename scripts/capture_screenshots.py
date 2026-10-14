"""Script to capture dashboard screenshots using Chrome DevTools Protocol (CDP)."""

import asyncio
import base64
import json
import os
import urllib.request
import websockets

SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

TABS = [
    ("overview_insights.png", 0, "Automated Insights & Regional Overview"),
    ("pollutant_trends.png", 1, "Pollutant Trends (PM2.5, PM10, Gaseous)"),
    ("station_comparisons.png", 2, "Station Comparisons"),
    ("data_explorer.png", 3, "Interactive Data Explorer with CSV Download"),
    ("statistical_anomalies.png", 4, "Statistical Anomalies"),
    ("pipeline_health.png", 5, "Pipeline Health & Quality Audits"),
]

async def send_cdp(ws, method, params=None, msg_id=[1]):
    curr_id = msg_id[0]
    msg_id[0] += 1
    req = {"id": curr_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(req))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == curr_id:
            return resp.get("result", {})

async def main():
    target_url = "http://localhost:8502"
    # Create new target
    req = urllib.request.Request(f"http://localhost:9222/json/new?{target_url}", method="PUT")
    with urllib.request.urlopen(req) as response:
        target = json.loads(response.read().decode())
    
    ws_url = target["webSocketDebuggerUrl"]
    target_id = target["id"]
    print(f"Connected to CDP page target: {target_id}")

    try:
        async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
            # Enable Page and Runtime
            await send_cdp(ws, "Page.enable")
            await send_cdp(ws, "Runtime.enable")
            
            # Set Viewport
            await send_cdp(ws, "Emulation.setDeviceMetricsOverride", {
                "width": 1440,
                "height": 1050,
                "deviceScaleFactor": 1,
                "mobile": False,
            })

            print("Waiting 6 seconds for initial Streamlit dashboard render...")
            await asyncio.sleep(6)

            for filename, tab_idx, label in TABS:
                print(f"Navigating to Tab {tab_idx}: {label}...")
                if tab_idx > 0:
                    click_js = f"""
                    (function() {{
                        const tabs = document.querySelectorAll('div[data-testid="stTab"]');
                        if (tabs && tabs[{tab_idx}]) {{
                            tabs[{tab_idx}].scrollIntoView({{ behavior: 'instant', block: 'center' }});
                            tabs[{tab_idx}].click();
                            return true;
                        }}
                        return false;
                    }})()
                    """
                    res = await send_cdp(ws, "Runtime.evaluate", {"expression": click_js, "returnByValue": True})
                    print(f"  Clicked tab {tab_idx}, result: {res.get('result', {}).get('value')}")
                    # Allow Streamlit to re-render charts
                    await asyncio.sleep(4)

                # Capture screenshot
                shot_resp = await send_cdp(ws, "Page.captureScreenshot", {"format": "png"})
                img_data = base64.b64decode(shot_resp["data"])
                out_path = os.path.join(SCREENSHOT_DIR, filename)
                with open(out_path, "wb") as f:
                    f.write(img_data)
                print(f"  Captured {filename} ({len(img_data)} bytes)")

    finally:
        # Close target
        close_req = urllib.request.Request(f"http://localhost:9222/json/close/{target_id}")
        urllib.request.urlopen(close_req)
        print("Page target closed.")

if __name__ == "__main__":
    asyncio.run(main())
