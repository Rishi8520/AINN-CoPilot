package app.scenarios;

import simu5g.simulations.nr.networks.SingleCell_Standalone;
import simu5g.simulations.nr.networks.MultiCell_Standalone;

network TelcoMindSingleCell extends SingleCell_Standalone
{
    @display("bgb=1000,1000");
}

network TelcoMindMultiCell extends MultiCell_Standalone
{
    @display("bgb=1200,800");
}
