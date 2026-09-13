import os, resource, time, json
os.environ["ECON_STATE"] = "/tmp/econ/ensur-economy/econ_state_1m"
os.environ["ECON_POP_N"] = "1000000"
t0 = time.time()
import continuous
if not os.path.exists(continuous.POP):
    continuous.init_state(); print("state initialized", flush=True)
continuous.advance_cycle()
out = {"elapsed_s": round(time.time()-t0), "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6, 2)}
print("TELEMETRY", json.dumps(out), flush=True)
