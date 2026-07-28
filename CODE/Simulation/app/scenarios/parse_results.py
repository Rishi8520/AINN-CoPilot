import re
import os

SCA="/workspace/app/scenarios/results/normal_operation.sca"

def extract():
    metrics={}

    with open(SCA,"r") as f:
        data=f.read()

    patterns={
        "packet_sent_count":
        r"server\.udp packetSent:count ([0-9\.]+)",

        "packet_sent_bytes":
        r"server\.udp packetSent:sum\(packetBytes\) ([0-9\.]+)",

        "handover_count":
        r"handover.*count ([0-9\.]+)",

        "x2_messages":
        r"x2App.* ([0-9\.]+)$"
    }

    for k,p in patterns.items():
        m=re.search(p,data,re.MULTILINE)
        if m:
            metrics[k]=float(m.group(1))
        else:
            metrics[k]=0

    if metrics["packet_sent_count"]>0:
        metrics["throughput_mbps"]=(
            metrics["packet_sent_bytes"]*8/20/1e6
        )
    else:
        metrics["throughput_mbps"]=0

    return metrics


if __name__=="__main__":
    print(extract())
