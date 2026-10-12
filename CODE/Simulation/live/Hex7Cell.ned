// Adapted from Simu5G's SingleCell_Standalone / MultiCell_Standalone.
// Copyright (C) 2019-2021 Giovanni Nardini, Giovanni Stea, Antonio Virdis et al. (University of Pisa)
// Copyright (C) 2022-2026 Giovanni Nardini, Giovanni Stea et al. (University of Pisa)
// This file is part of a software released under the license included in file
// "license.pdf". Please read LICENSE and README files before using it.
// The above files and the present reference are part of the software itself,
// and cannot be removed from it. Upstream licenses are retained in /opt/simu5g.
package telcomind;

import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.networklayer.ipv4.RoutingTableRecorder;
import inet.node.ethernet.Eth10G;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import simu5g.common.binder.Binder;
import simu5g.common.carrierAggregation.CarrierAggregation;
import simu5g.nodes.NrUe;
import simu5g.nodes.gNodeB;
import simu5g.nodes.Upf;
import simu5g.world.radio.LteChannelControl;

network Hex7Cell
{
    parameters:
        int numUe = default(10);
        bool useX2 = default(false);
    submodules:
        channelControl: LteChannelControl;
        routingRecorder: RoutingTableRecorder;
        configurator: Ipv4NetworkConfigurator;
        binder: Binder;
        carrierAggregation: CarrierAggregation;
        server: StandardHost;
        router: Router;
        upf: Upf;
        iUpf: Upf;
        gnb[7]: gNodeB;
        ue[numUe]: NrUe;
    connections:
        server.pppg++ <--> Eth10G <--> router.pppg++;
        router.pppg++ <--> Eth10G <--> upf.filterGate;
        upf.pppg++ <--> Eth10G <--> iUpf.pppg++;
        for i=0..6 {
            iUpf.pppg++ <--> Eth10G <--> gnb[i].ppp;
        }
        for i=0..6, for j=i+1..6 {
            gnb[i].x2++ <--> Eth10G <--> gnb[j].x2++ if useX2;
        }
}
