package app.scenarios;

import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.node.ethernet.Eth10G;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import simu5g.common.binder.Binder;
import simu5g.common.carrierAggregation.CarrierAggregation;
import simu5g.nodes.Ue;
import simu5g.nodes.gNodeB;
import simu5g.world.radio.ChannelControl;

network TelcoNetTopology
{
    parameters:
        @display("bgb=1000,700;bg=white");
    submodules:
        channelControl: ChannelControl {
            @display("p=100,80;is=s");
        }
        binder: Binder {
            @display("p=220,80;is=s");
        }
        carrierAggregation: CarrierAggregation {
            @display("p=360,80;is=s");
        }
        configurator: Ipv4NetworkConfigurator {
            @display("p=500,80;is=s");
        }
        
        // Remote Data Server (Application Source / Content Provider)
        server: StandardHost {
            @display("p=150,350;i=device/server");
        }
        
        // Core Transport Edge Router
        coreRouter: Router {
            @display("p=350,350;i=device/router");
        }
        
        // 3GPP RAN Base Station Tower 
        gNodeB1: gNodeB {
            @display("p=600,350;i=device/antennatower");
        }
        
        // Mobile User Equipment Nodes Array
        ue[4]: Ue {
            @display("p=850,200,m=g,150,150;i=device/pocketpc");
        }
    connections:
        // Core Network Infrastructure backbone fiber mappings
        server.ethg++ <--> Eth10G <--> coreRouter.ethg++;
        coreRouter.ethg++ <--> Eth10G <--> gNodeB1.ppp;
}
