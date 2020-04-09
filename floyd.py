from ryu.base import app_manager
from ryu.controller import mac_to_port
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib import mac
from ryu.topology.api import get_switch, get_link
from ryu.app.wsgi import ControllerBase
from ryu.topology import event, switches
from collections import defaultdict


topo3 = {1: {1: 0, 2: 64, 3: float('inf'), 4: 10, 5: float('inf')},
         2: {1: 64, 2: 0, 3: float('inf'), 4: float('inf'), 5: 10},
         3: {1: float('inf'), 2: float('inf'), 3: 0, 4: 10, 5: 64},
         4: {1: 10, 2: float('inf'), 3: 10, 4: 0, 5: float('inf')},
         5: {1: float('inf'), 2: 10, 3: 64, 4: float('inf'), 5: 0}
         }

topo1 = {
    1: {1: 0, 2: 1, 3: float('inf'), 4: float('inf'), 5: float('inf'), 6: float('inf'), 7: 10, 8: 64, 9: float('inf'),
        10: float('inf')},
    2: {1: 1, 2: 0, 3: 1, 4: float('inf'), 5: float('inf'), 6: 133, 7: 64, 8: float('inf'), 9: float('inf'),
        10: float('inf')},
    3: {1: float('inf'), 2: 1, 3: 0, 4: 10, 5: 10, 6: float('inf'), 7: float('inf'), 8: float('inf'), 9: float('inf'),
        10: float('inf')},
    4: {1: float('inf'), 2: float('inf'), 3: 10, 4: 0, 5: 64, 6: 1, 7: float('inf'), 8: float('inf'), 9: float('inf'),
        10: float('inf')},
    5: {1: float('inf'), 2: float('inf'), 3: 10, 4: 64, 5: 0, 6: float('inf'), 7: float('inf'), 8: float('inf'),
        9: float('inf'), 10: 1},
    6: {1: float('inf'), 2: 64, 3: float('inf'), 4: 1, 5: float('inf'), 6: 0, 7: 10, 8: float('inf'), 9: float('inf'),
        10: 64},
    7: {1: 10, 2: 64, 3: float('inf'), 4: float('inf'), 5: float('inf'), 6: 10, 7: 0, 8: 64, 9: 10, 10: float('inf')},
    8: {1: 64, 2: float('inf'), 3: float('inf'), 4: float('inf'), 5: float('inf'), 6: float('inf'), 7: 64, 8: 0, 9: 10,
        10: float('inf')},
    9: {1: float('inf'), 2: float('inf'), 3: float('inf'), 4: float('inf'), 5: float('inf'), 6: float('inf'), 7: 10,
        8: 64, 9: 0, 10: float('inf')},
    10: {1: float('inf'), 2: float('inf'), 3: float('inf'), 4: float('inf'), 5: 1, 6: 64, 7: float('inf'),
         8: float('inf'), 9: float('inf'), 10: 0}
}

topo2 = {
    1: {1: 0, 2: float('inf'), 3: float('inf'), 4: float('inf'), 5: 10, 6: 64, 7: float('inf')},
    2: {1: float('inf'), 2: 0, 3: float('inf'), 4: float('inf'), 5: 10, 6: float('inf'), 7: 64},
    3: {1: float('inf'), 2: float('inf'), 3: 0, 4: float('inf'), 5: float('inf'), 6: 10, 7: 1},
    4: {1: float('inf'), 2: float('inf'), 3: float('inf'), 4: 0, 5: float('inf'), 6: float('inf'), 7: 64},
    5: {1: 10, 2: 10, 3: float('inf'), 4: float('inf'), 5: 0, 6: float('inf'), 7: float('inf')},
    6: {1: 64, 2: float('inf'), 3: 10, 4: float('inf'), 5: float('inf'), 6: 0, 7: float('inf')},
    7: {1: float('inf'), 2: 64, 3: 1, 4: 64, 5: float('inf'), 6: float('inf'), 7: 0}
}

#switches
switches = []
#mymac[srcmac]->(switch, port)
mymac={ }
#adjacency map [sw1][sw2]->port from sw1 to sw2
adjacency=defaultdict(lambda:defaultdict(lambda:None))


def get_path (graf, src,dst,first_port,final_port):
    distance = defaultdict(lambda: defaultdict(lambda: None))
    topo = graf
    switch = set(topo)
    prev = defaultdict(lambda: defaultdict(lambda: None))

    for i in switch:
        for j in switch:
            if topo[i][j] != float('inf'):
                prev[i][j] = j
                distance[i][j]=topo[i][j]
                #print "topo: ",topo[i][j],"D: ",distance[i][i]
            else:
                distance[i][j]=float('inf')

    for k in switch:
        for i in switch:
            for j in switch:
                if distance[i][j] > distance[i][k] + distance[k][j]:
                    distance[i][j] = distance[i][k] + distance[k][j]
                    prev[i][j] = prev[i][k]


    if prev[src][dst] is None:
        return []
    path = [src]
    if src != dst:
        while path[-1] != dst:
            path.append(prev[path[-1]][dst])
    else:
        path = [src]

    print 'path: ',path, 'total distance: ',distance[src][dst]

    r = []
    in_port = first_port
    for s1,s2 in zip(path[:-1],path[1:]):
        out_port = adjacency[s1][s2]
        r.append((s1,in_port,out_port))
        in_port = adjacency[s2][s1]
    r.append((dst,in_port,final_port))
    #print "r: ",r
    return r

class ProjectController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    def __init__(self, *args, **kwargs):
        super(ProjectController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.topology_api_app = self
        self.datapath_list=[]
    # Function that lists all attributes in the given object
    def ls(self,obj):
        print("\n".join([x for x in dir(obj) if x[0] != "_"]))
    def add_flow(self, datapath, in_port, dst, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = datapath.ofproto_parser.OFPMatch(in_port=in_port, eth_dst=dst)
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(datapath=datapath, match=match, cookie=0,command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,priority=ofproto.OFP_DEFAULT_PRIORITY, instructions=inst)
        datapath.send_msg(mod)
    def install_path(self, p, ev, src_mac, dst_mac):
        shortest_path_route = ""
        for z in p:
            shortest_path_route += str(z[0])+"-"
            print ""+str(z)
		#printing the shortest path route
        print "path=", shortest_path_route, " src_mac=", src_mac, " dst_mac=", dst_mac
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        for sw, in_port, out_port in p:
            #print src_mac,"->", dst_mac, "via ", sw, " in_port=", in_port, " out_port=", out_port
            match=parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
            actions=[parser.OFPActionOutput(out_port)]
            datapath=self.datapath_list[int(sw)-1]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS , actions)]
            mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath, match=match, idle_timeout=0, hard_timeout=0,priority=1, instructions=inst)
            datapath.send_msg(mod)
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures , CONFIG_DISPATCHER)
    def switch_features_handler(self , ev):
        print "switch_features_handler is called"
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS ,actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(
        datapath=datapath, match=match, cookie=0,
        command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,priority=0, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        #print "eth.ethertype=", eth.ethertype
        #avodi broadcast from LLDP
        if eth.ethertype==35020:
            return
        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        if src not in mymac.keys():
            mymac[src]=( dpid,  in_port)
            #ganti topo
        if dst in mymac.keys():
            p = get_path(topo1, mymac[src][0], mymac[dst][0], mymac[src][1], mymac[dst][1])
            #print p
            self.install_path(p, ev, src, dst)
            out_port = p[0][2]
        else:
            out_port = ofproto.OFPP_FLOOD
        actions = [parser.OFPActionOutput(out_port)]
        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
        data=None
        if msg.buffer_id==ofproto.OFP_NO_BUFFER:
            data=msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,actions=actions, data=data)
        datapath.send_msg(out)
	# EventSwitchEnter triggers get_topology_data method
    @set_ev_cls(event.EventSwitchEnter)
    def get_topology_data(self, ev):
        global switches
		#List of switch objects from topology
        switch_list = get_switch(self.topology_api_app, None)
        switches=[switch.dp.id for switch in switch_list]
        self.datapath_list=[switch.dp for switch in switch_list]
        #print "self.datapath_list=", self.datapath_list
        print "switches=", switches
		#List of link objects from topology
        links_list = get_link(self.topology_api_app, None)
        mylinks=[(link.src.dpid,link.dst.dpid,link.src.port_no,link.dst.port_no) for link in links_list]
        for s1,s2,port1,port2 in mylinks:
            adjacency[s1][s2]=port1
            adjacency[s2][s1]=port2
            #print s1,s2,port1,port2
