#!/usr/bin/python

from __future__ import division

from copy import deepcopy

import matplotlib.pyplot as plt
import networkx   as nx
import numpy      as np
import random     as rnd
import statistics as stats

import os
import sys

from scipy.spatial import distance
from tabulate import tabulate
import xml.etree.ElementTree as ElementTree
from xml.dom import minidom

## Type constants to check against for input verification
BOOL = type( bool()  )
STR  = type( str()   )
INT  = type( int()   )
FLT  = type( float() )
LST  = type( list()  )
DCT  = type( dict()  )

## Admissible keywords for topology parameter
TOPOLOGIES = [ '',
               'complete',
               'cycle',
               'random',
               'scale free',
               'small world',
               'star' ]

## Encode 2D matrix as string with # delimiting comma-delimited rows
def matrix_to_string( m ):
    s = ''
    for row in m:
        for elem in row: s += '%s,' % elem
        s = s[:-1] + '#'
    return s[:-1]

def string_to_matrix( s ):
    ret = []
    split = s.split( '#' )
    for line in split:
        splitline = string_to_vector( line )
        ret.append( splitline )
    return np.array( ret )

## Encode vector as comma-delimited string
def vector_to_string( v ):
    s = ''
    for elem in v: s += '%s,' % elem
    return s[:-1]

def string_to_vector( s ):
    split = s.split( ',' )
    if split == ['']: return []
    return [ float( i ) for i in split ]

## Special encoding for reading/writing mask matrices.
## Since rows are binary, just encode them as base 10 numbers to save
## space.
def encode_mask( masks ):
    s = ''
    for i in range(len(masks)):
        if not any( masks[i] ): continue
        s += str(i) + ','
        temp = ''
        for j in range( len( masks[i] ) ):
            if masks[i][j] == 0.0: temp += '0'
            else:                  temp += '1'
        s += '%d#' % int(temp, 2)
    return s[:-1]

## Take encoded mask entries
def decode_mask( mask ):
    return [ int(i) for i in str( bin( int( mask ) ) )[2:] ]

## The SocialNetworkModel class
class SocialNetwork():

    ## Always initialize class with a properties dictionary
    def __init__( self, props=None ):

        ## Error checking on properties input
        if type(props) is not DCT:
            self._log( 'Properties argument must be a dictionary.' )
            return

        self._properties = props
        self._graph      = None

        ## Verify that all properties are present and correctly formatted.
        ## Fill in any missing properties with default values.
        self._validate_input( props )

        ## Seed the RNG if one is passed in the properties dictionary
        if 'seed' in props:
            rnd.seed( props['seed'] )
            self._log( 'Set random seed to: %s' % props['seed'] )

        if 'file' in self._properties: self._read( self._properties['file'] )
        else: self._build()

    ## A function to log basic interactions.  Used to keep track of parameter
    ## settings and input/output file locations, etc.
    def _log( self, msg ):
        
        if type(msg) is not STR:
            pass
        print( msg )

    ## Build a new graph from given properties.
    def _build( self ):

        topology = self._properties['topology']

        if topology in TOPOLOGIES:   self.generate_edges( topology )
        else: self.log( 'An error occurred generating edges.\nPlease check input properties and try again.' )

        self.initialize_edge_weights()
        self.initialize_attribute_space()
        self.initialize_correlations()
        self.initialize_masks()
        self.mix_network()
        self.initialize_resistance()

    def _read( self, filename ):

        if '.xml' not in filename: filename += '.xml'
        if not os.path.exists( filename ):
            self._log( 'Cannot find file: %s' % filename )
            return

        print( 'Reading file: %s' % filename )

        tree = ElementTree.parse( os.path.join( os.getcwd(), filename ) )
        root = tree.getroot()

        for a in root.attrib:
            ## Matrices
            if a in [ 'attribute_space', 'correlations' ]:
                self._properties[a] = string_to_matrix( root.attrib[a] )
            ## Float lists
            elif a in ['resistance']:
                self._properties[a] = [ float(i) for i in root.attrib[a].split(',') ]
            ## Ints
            elif a in [ 'dimensions', 'seed', 'n' ]:
                self._properties[a] = int( root.attrib[a] )
            ## Floats
            elif a in [ 'friend', 'unfriend', 'rewire',
                        'saturation', 'weight', 'update' ]:
                try:
                    self._properties[a] = float( root.attrib[a] )
                except:
                    self._properties[a] = root.attrib[a]
            ## Bools
            elif a in [ 'directed', 'symmetric' ]:
                self._properties[a] = bool( root.attrib[a] )
            ## String lists
            elif a in [ 'types' ]:
                self._properties[a] = root.attrib[a].split( ',' )
            ## Dictionaries
            elif a in [ 'type_dist', 'indexes_by_type' ]:
                self._properties[a] = eval( root.attrib[a] )
            elif a == 'resistance_param':
                if root.attrib[a] == 'random':
                    self._properties[a] = 'random'
                else:
                    try:
                        self._properties[a] = float( root.attrib[a] )
                    except:
                        self._properties[a] = eval( root.attrib[a] )
            else:
                self._properties[a] = root.attrib[a]

        ## Set up NetworkX graph underneath
        if self._properties['directed']: self._graph = nx.DiGraph()
        else:                            self._graph = nx.Graph()

        ## Add nodes to graph
        self._graph.add_nodes_from( range( self._properties['n'] ) )

        self.initialize_edge_weights()
        self.initialize_masks()
##        self.initialize_resistance()

        for child in root:

            idx = int( child.attrib['idx'] )
            if not child.attrib['parents']: parents = []
            else: parents = [ int( i ) for i in string_to_vector( child.attrib['parents'] ) ]
            for p in parents:
                self._graph.add_edge( idx, p )
                
            for a in child.attrib:

                if a in [ 'idx', 'parents' ]:
                    continue
                elif a == 'weights':
                    weights = string_to_vector( child.attrib[a] )
                    for i in range( len( parents ) ):
                        self._properties[ 'weights' ][parents[i]][idx] = weights[i]
                    self.update_weight_column( idx )
                elif a == 'masks':
                    masks = string_to_matrix( child.attrib['masks'] )
                    for line in masks:
                        parent = int( line[0] )
                        mask = decode_mask( line[1] )
                        for k in range( len( mask ) ):
                            if mask[k] == 0:
                                self._properties['masks'][idx][parent][k] = mask[k]
                            else:
                                self._properties['masks'][idx][parent][k] = self._properties['attribute_space'][parent][k]

    def _save( self, filename ):

        ## Make sure filename ends in xml
        if '.xml' not in filename: filename += '.xml'
        self._log( 'Writing network to %s' % os.path.join( os.getcwd(), filename ) )

        ## Set up a dictionary that will store different encodings for
        ## attributes of different types.
        attr = {}
        for key in self._properties:
            if key in [ 'attribute_space', 'correlations' ]:
                attr[key] = matrix_to_string( self._properties[key] )
            elif key in [ 'types', 'resistance' ]:
                attr[key] = vector_to_string( self._properties[key] )
            ## Skip over these because they get written out at the Node level.
            elif key in [ 'weights', 'normalized_weights', 'masks' ]:
                continue
            else:
                attr[key] = str( self._properties[key] )

        root = ElementTree.Element( 'Graph', attrib=attr )

        for i in range( self._properties['n'] ):

            props = { 'idx' : str( i ) }
            props['parents'] = vector_to_string( self.get_neighbors( i ) )
            props['masks']   = encode_mask( self._properties['masks'][i] )
            props['weights'] = vector_to_string( [ self._properties['weights'][i][j] for j in self.get_neighbors(i) ] )

            node = ElementTree.SubElement( root, 'Node', attrib=props )

        f = open( filename, 'w' )
        xml_raw = ElementTree.tostring( root ).decode('utf-8')
        xml_out = minidom.parseString( xml_raw )
        f.write( xml_out.toprettyxml( indent=" ") )
        f.close()

    def _validate_input( self, props ):

        ## Check property dictionary for standard entries, and fill in any gaps with
        ## default values.
        if 'n' not in props: self._properties['n'] = 0
        if 'directed' not in props: self._properties['directed'] = False
        if 'symmetric' not in props: self._properties['symmetric'] = False
        elif props['symmetric']: self._properties['directed'] = True
        if 'topology' not in props: self._properties['topology'] = ''
        if 'saturation' not in props: self._properties['saturation'] = 0.1
        if 'dimensions' not in props: self._properties['dimensions'] = 1
        if 'visibility' not in props: self._properties['visibility'] = 'visible'
        if 'weight' not in props: self._properties['weight'] = 1.0
        if 'unfriend' not in props: self._properties['unfriend'] = 1.0
        if 'update' not in props: self._properties['update'] = 1.0
        if 'resistance_param' not in props: self._properties['resistance_param'] = 0.0
        
    def generate_edges( self, topology ):

        ## Prepare RNG seed for edge generation algorithms
        if 'seed' in self._properties: SEED = self._properties['seed']
        else: SEED = None

        topology = self._properties['topology']
        self._log( 'Generating edges from [ %s ]' % topology )

        ## Initialize networkx graph based on user's preference of directed/not
        if self._properties['directed']: self._graph = nx.DiGraph()
        else:                            self._graph = nx.Graph()
        self._log( 'Setting directed=%s' % self._properties['directed'] )

        ## Generate nodes
        self._graph.add_nodes_from( range( self._properties['n'] ) )
        self._log( 'Created %d nodes.' % self._properties['n'] )

        ## Case for blank graph.
        if topology == '': return

        ## Generate a set of edges based on the topology requested
        if topology == 'random':
            self._log( 'Constructing Erdos Renyi random graph.' )
            edges = nx.erdos_renyi_graph( self._graph.number_of_nodes(),
                                          self._properties['saturation'],
                                          directed=self._properties['directed'],
                                          seed=SEED ).edges()

        elif topology == 'scale free':
            self._log( 'Constructing scale free graph.' )
            edges = nx.scale_free_graph( self._graph.number_of_nodes(),
                                         seed=SEED ).edges()

        elif topology == 'small world':
            self._log( 'Constructing small world graph.' )
            n     = self._graph.number_of_nodes()
            sat   = self._properties['saturation']
            edges = nx.watts_strogatz_graph( n, int( sat * n ),
                                             self._properties['rewire'],
                                             seed=SEED ).edges()

        elif topology == 'star':
            self._log( 'Constructing star graph.' )
            n     = self._graph.number_of_nodes()
            edges = nx.star_graph( n ).edges()

        elif topology == 'complete':
            self._log( 'Constructing complete graph.' )
            n     = self._graph.number_of_nodes()
            edges = nx.complete_graph( n ).edges()
            
        elif topology == 'cycle':
            self._log( 'Constructing complete graph.' )
            n     = self._graph.number_of_nodes()
            edges = nx.cycle_graph( n ).edges()
            
        ## Add generated edges to graph structure
        for e in edges:
            self._graph.add_edge( e[0], e[1] )
            ## Add opposite edges if network should be symmetric
            if self._properties['symmetric']: self._graph.add_edge( e[1], e[0] )

    def initialize_edge_weights( self ):

        ## Initialize blank n x n matrices to hold raw and normalized values for
        ## edge weights.  Raw values can be between 0 and 1.  After normalization,
        ## the sum of edge weights coming into a node must equal 1.
        n = self._properties['n']
        self._properties['weights'] = np.zeros( ( n, n ) )
        self._properties['normalized_weights'] = np.zeros( ( n, n ) )

        for u in self._graph.nodes():
            nbrs = self.get_neighbors( u )
            for v in nbrs:
                
                if self._properties['weights'][v][u] > 0: continue
                if self._properties['weight'] == 'random':
                    self._properties['weights'][v][u] = rnd.random()
                else:
                    self._properties['weights'][v][u] = self._properties['weight']
                if not self._properties['directed']:
                    self._properties['weights'][u][v] = self._properties['weights'][v][u]
                    
            self._properties['weights'][u][u] = 1.

            ## Once all raw weights have been initialized, populate the
            ## appropriate normalized weight column.
            self.update_weight_column( u )

        if abs( sum( self._properties['normalized_weights'].sum(axis=0) ) - \
                     self._properties['n'] ) > 0.00001:
            self._log( 'Edge weights appear to be corrupted.' )

    ## Initialize each node's values in diffusion dimensions.
    def initialize_attribute_space( self ):
        k = self._properties['dimensions']
        matrix = [ [ rnd.choice( [ -1., 1. ] ) for j in range(k) ] \
                     for i in range( self._properties['n'] ) ]
        self._properties['attribute_space'] = np.array( matrix )
        self._log( 'Set initial diffusion values.' )

    ## Initialize a matrix representing levels of correlation between dimensions in
    ## attribute space.
    def initialize_correlations( self ):
        self._properties['correlations'] = np.identity( self._properties['dimensions'] )

    ## Initialize all masks, determining which attributes are revealed to which neighbors.
    def initialize_masks( self ):

        n = self._properties['n']
        K = self._properties['dimensions']
        vis = self._properties['visibility']

        self._properties['masks'] = np.zeros( ( n, n, K ) )

        for i in range( n ):
            
            for k in range( K ):
                self._properties['masks'][i][i][k] = self._properties['attribute_space'][i][k]
                
            nbrs = self.get_neighbors( i )
            for j in nbrs:
                if vis == 'random':
                    for k in range( K ):
                        self._properties['masks'][j][i][k] = rnd.choice( [ 0., self._properties['attribute_space'][i][k] ] )
                elif vis == 'visible':
                    for k in range( K ):
                        self._properties['masks'][j][i][k] = self._properties['attribute_space'][i][k]
        self._log( 'Set initial mask values with condition \'%s\'.' % vis )

    def initialize_resistance( self ):

        n = self._properties['n']
        self._properties['resistance'] = np.zeros( n )
        myparam = self._properties['resistance_param']

        if type( myparam ) is DCT:
            for key in myparam:
                if key in [i for i in self._properties['type_dist']]:
                    idxs = self._properties['indexes_by_type'][key]
                    for idx in idxs:
                        if myparam[key] == 'random':
                            self._properties['resistance'][idx] = rnd.random()
                        if type( myparam[key] ) is FLT:
                            if myparam[key] < 0. or myparam[key] > 1.:
                                print( 'Resistance for [%s] must be between 0 and 1.' % myparam[key] )
                                print( '\tInvalid value: %f' % myparam[key] )
                                break
                            self._properties['resistance'][idx] = myparam[key]
                else:
                    print( 'Type [%s] does not match any key in type_dist.  Skipping.' % key )
        if type( myparam ) is FLT:
            for i in range( n ):
                self._properties['resistance'][i] = myparam
        if type( myparam ) is STR:
            if myparam == 'random':
                for i in range( n ):
                    self._properties['resistance'][i] = rnd.random()

    ## Use the property type_dist to randomly assign agents an archetype.
    def mix_network( self ):

        n = self._properties['n']
        self._properties['types'] = []
        self._properties['indexes_by_type'] = {}

        if 'type_dist' not in self._properties:
            self._properties['type_dist'] = { 'default' : 1. }
            return

        min_num = 99999999
        min_t = ''

        nums = {}
        d = self._properties['type_dist']

        if abs( sum( [ d[key] for key in d ] ) - 1. ) > .000001:
            print( 'Agent type proportions must sum to 1.' )
            return

        for t in d:
            
            self._properties['indexes_by_type'][t] = []
            nums[t] = int( d[t] * n )
            
            ## This is just to correct any off-by-ones when we get done filling the type
            ## vector.
            if nums[t] <= min_num:
                min_num = nums[t]
                min_t = t

            ## Append nums[t] copies of this type's string representation to the vector.
            for i in range( nums[t] ):
                self._properties['types'].append( t )

        ## Make sure that the rounding above didn't leave us short an element.
        while len( self._properties['types'] ) < n:
            nums[min_t] += 1
            self._properties['types'].append( min_t )

        rnd.shuffle( self._properties['types'] )
        for i in range( len( self._properties['types'] ) ):
            self._properties['indexes_by_type'][self._properties['types'][i]].append( i )

        print( 'Distributed agent types in network.' )
        for t in nums:
            print( "\t'%s':\t%d" % ( t, nums[t] ) )

    ## Retrieves all nodes that influence u.  In directed graphs, these are all nodes
    ## with edges leading to u.  In undirected graphs, these are all nodes adjacent
    ## to u.
    def get_neighbors( self, u ):
        
        if not self._properties['directed']: return self._graph.neighbors( u )
        else:                                return self._graph.predecessors( u )

    ## Update normalized weight column for node u after making a new connection or
    ## deleting an old one.
    def update_weight_column( self, u ):

        ## Zero out row first in case someone unfriended
        for v in range( self._properties['n'] ):
            self._properties['normalized_weights'][v][u] = 0.

        ## Calculate the total amount of influence u receives, then assign each of
        ## its neighbors v a weight equal to v's proportional contribution.
        total = self._properties['weights'].sum(axis=0)[u]
        
        nbrs = self.get_neighbors( u )
        for v in nbrs:
            self._properties['normalized_weights'][v][u] = self._properties['weights'][v][u] / total
        self._properties['normalized_weights'][u][u] = 1. / total

    ## Get the local average over diffusion dimensions for the neighborhood of node u.
    ## If the average is weighted by corresponding edges, then the matrix
    ## self._properties['normalized_weights'] is used to calculate the average.
    ## Otherwise, calculate a simple arithmetic average.
    def get_local_average( self, u, weighted=False ):

        if weighted:
            return self._properties['normalized_weights'].T[u].dot( self._properties['masks'][u] ).round( decimals=2 )
        else:
            num_nbrs = len( list( self.get_neighbors( u ) ) )
            return self._properties['masks'][u].sum(axis=0) / ( num_nbrs + 1)

    ## Get average values for all diffusion dimensions for the entire network.  If the
    ## argument t is not None, it should be the name of an agent archetype, and the function
    ## will return the global average across only agents of that type.
    def get_global_average( self, t=None ):

        if t is None: return self._properties['attribute_space'].mean(axis=0)

        matrix = [ self._properties['attribute_space'][i] \
                   for i in self._properties['indexes_by_type'][t] ]
        return np.array( matrix ).mean( axis=0 )
        

    def get_reward_for_neighbor( self, u, v ):

        vec1 = self._properties['attribute_space'][u]
        vec2 = self._properties['masks'][u][v]

        distvec1 = [ vec1[i] for i in range( len( vec1 ) ) if vec2[i] != 0. ]
        if not distvec1: return 0.
        distvec2 = [ vec2[i] for i in range( len( vec2 ) ) if vec2[i] != 0. ]

        dist = distance.hamming( distvec1, distvec2 )

        if self._properties['types'][u] in [ 'R' , 'DA' ]:
            return 1 - dist
        if self._properties['types'][u] in [ 'E' , 'RWC' ]:
            return dist
        if self._properties['types'][u] in [ 'SC' , 'SR' ]:
            return 1 - ( abs(dist - 0.5) * 2 )

    def get_reward_for_node( self, u ):

        rewards = [ self.get_reward_for_neighbor( u, v ) for v in self.get_neighbors( u ) ]
        if not rewards: return 0.
        else: return stats.mean( rewards )

    def disconnect( self, u, v ):
        ## Remove edge from underlying graph.
        ## Set masks back to 0.
        ## Recalculate weights for u and v.

        ## Chance of not deleting link.
        if rnd.random() < self._properties['unfriend']: return
        
        try:
            self._graph.remove_edge( u, v )
            for k in range( self._properties['dimensions'] ):
                self._properties['masks'][v][u][k] = 0.
                self._properties['masks'][u][v][k] = 0.
        except:
            pass
        
        try:
            if self._properties['symmetric']: self._graph.remove_edge( v, u )
        except:
            pass

        self._properties['weights'][u][v] = 0.
        self._properties['weights'][v][u] = 0.
        self.update_weight_column( u )
        self.update_weight_column( v )

    def connect( self, u, v ):

        if u == v: return
        
        ## Add edge to graph structure
        self._graph.add_edge( u, v )

        ## Change influence scores in self._influence
        if self._properties['weight'] == 'random':
            self._properties['weights'][u][v] = rnd.random()
        else:
            self._properties['weights'][u][v] = self._properties['weight']

        ## Change masks based on visibility
        if self._properties['visibility'] == 'visible':
            for k in range( self._properties['dimensions'] ):
                self._properties['masks'][v][u][k] = self._properties['attribute_space'][u][k]
                
        elif self._properties['visibility'] == 'random':
            for k in range( self._graph.graph['k'] ):
                self._masks[v][u][k] = rnd.choice( [ 0., self._properties['attribute_space'][u][k] ] )

        ## If the graph is symmetric, do the same in the other direction
        if self._properties['symmetric']:
            self._graph.add_edge( v, u )
            
            if self._properties['weight'] == 'random':
                self._properties['weights'][v][u] = rnd.random()
            else: self._properties['weights'][v][u] = self._properties['weight']
            
            if self._properties['visibility'] == 'visible':
                for k in range( self._properties['dimensions'] ):
                    self._properties['masks'][u][v][k] = self._properties['attribute_space'][v][k]
            elif self._properties['visibility'] == 'random':
                for k in range( self._graph.graph['k'] ):
                    self._properties['masks'][u][v][k] = rnd.choice( [ 0., self._properties['attribute_space'][v][k] ] )

        ## Update proportional weights
        self.update_weight_column( u )
        self.update_weight_column( v )

    def reveal( self, u, v, k ):
        self._properties['masks'][v][u][k] = 1.

    def hide( self, u, v, k ):
        self._properties['masks'][v][u][k] = 0.

    def step( self ):

        self.update_attributes()
        self.act()
        self.network_effects()

    ## This function updates the attribute space according to update rules.
    def update_attributes( self ):

        changes = []

        for i in range( self._properties['n'] ):

            res = self._properties['resistance'][i]

            curr_state = self._properties['attribute_space'][i]
            local_avg = self.get_local_average( i )

            for k in range( len( curr_state ) ):

                if self._properties['types'][i] in [ 'R', 'E', 'SC' ]:
                    if curr_state[k] * local_avg[k] > 0: continue
                    else:
                        if abs( local_avg[k] ) > res:
                            if rnd.random() < self._properties['update']:
                                changes.append( [i,k] )
                if self._properties['types'][i] in ['DA', 'RWC', 'SR']:
                    if curr_state[k] * local_avg[k] < 0: continue
                    else:
                        if abs( local_avg[k] ) > res:
                            if rnd.random() < self._properties['update']:
                                changes.append( [i,k] )

        for [node, dim] in changes:
            self._properties['attribute_space'][node][dim] *= -1

    def act( self ):

        for i in range( self._properties['n'] ):

            nbrs = list( self.get_neighbors( i ) )
            for nbr in nbrs:
                r = self.get_reward_for_neighbor( i, nbr )
                if r < self._properties['unfriend_threshold']:

                    p = rnd.random()
                    if p < self._properties['unfriend']:
                        self.disconnect( i, nbr )

    def network_effects( self ):

        n = self._properties['n']
        for i in range( n ):
            candidates = set( [ int( rnd.random() * n ) for j in range( 5 ) ] )
            for c in candidates:
                p = rnd.random()
                if p < self._properties['friend']:
                    self.connect( c, i )

    def track_stat( self, stat='attributes', steps=100 ):

        x = range( steps + 1 )
        ys = []
        
        if stat == 'attributes': avg = self.get_global_average()
        if stat == 'degree': avg = nx.degree_centrality( self._graph )
        if stat == 'betweenness': avg = nx.betweenness_centrality( self._graph )
        if stat == 'closeness': avg = nx.closeness_centrality( self._graph )
        if stat == 'eigenvector': avg = nx.eigenvector_centrality( self._graph )

        if type( avg ) is DCT:
            for i in avg: ys.append( [ avg[i] ] )
        else:
            for i in avg: ys.append( [ i ] )

        for i in range( steps ):
            print( nx.density( self._graph ) )
            self.step()

            if stat == 'attributes': avg = self.get_global_average()
            if stat == 'degree': avg = nx.degree_centrality( self._graph )
            if stat == 'betweenness': avg = nx.betweenness_centrality( self._graph )
            if stat == 'closeness': avg = nx.closeness_centrality( self._graph )
            if stat == 'eigenvector': avg = nx.eigenvector_centrality( self._graph )

            if type( avg ) is DCT:
                for i in avg: ys[i].append( avg[i] )
            else:
                for i in range( len( avg ) ): ys[i].append( avg[i] )

        for i in range( len( ys ) ):
            plt.plot( x, ys[i] )
##            if self._properties['types'][i] == 'hom': plt.plot( x, ys[i], 'b' )
##            if self._properties['types'][i] == 'adv': plt.plot( x, ys[i], 'r' )
##            if self._properties['types'][i] == 'het': plt.plot( x, ys[i], 'g' )

        plt.ylim( [ -1.05, 1.05 ] )

        plt.show()

    def debug( self, frominherited=False, mycommand='' ):

        cmdline = mycommand
        cmd = ''
        
        while cmd != 'q':

            if not frominherited:
                cmd = input( '>>> ' )
                cmdline = cmd.split()

            ## Add cases for commands here
            ## Update the network according to the defined rules.
            if cmdline[0] == 'c':
                ## Update for one step
                if len( cmdline ) == 1:
                    print( 'Updating for one time step.' )
                    self.step()
                ## Update for a user-specified number of steps
                elif len( cmdline ) == 2:
                    try:
                        for i in range( int(cmdline[1]) ):
                            self.step()
                        print( 'Progressed network by %s time steps.' % cmdline[1] )
                    except:
                        print( 'Could not execute [%s] steps.' % cmdline[1] )

            ## Print out a list of possible commands
            elif cmdline[0] == 'help':
                print( 'SocialNetwork Commands:' )
                print( '\tshow attribute_space <list of nodes (optional)>' )
                print( '\tshow neighbors <list of nodes>' )
                print( '\tshow types <list of nodes (optional)>' )
                print( '\tshow resistance <list of nodes (optional)>' )
                print( '\tshow masks <node>' )
                print( '\tshow reward <node1> <node2>' )
                print( '\tshow global_average' )
                print( '\tshow local_average <list of nodes>' )
                print( '\tshow type_average <type>' )
                print( '\tset type <node> <type>' )
                print( '\tset resistance <resistance>' )
                print( '\tset resistance <node> <resistance>' )
                print( '\tset resistance <type> <resistance>' )
                print( '\tconnect <node1> <node2>' )
                print( '\tdisconnect <node1> <node2>' )
                print( '\treveal <node1> <node2> <dimension>' )
                print( '\thide <node1> <node2> <dimension>' )
                print( '\tsave <filename>' )

            elif cmdline[0] == 'draw':
                nx.draw( self._graph )

            ## Use 'show' at the beginning of a command to display the value of
            ## a graph attribute.
            elif cmdline[0] == 'show':
                
                if len( cmdline ) > 2: mylist = cmdline[2:]
                else: mylist = sorted( list( range( self._properties['n'] ) ) )

                if cmdline[1] == 'attribute_space':
                    entries = [ ['Node','Attributes'] ]
                    for i in mylist:
                        try:
                            entries.append( [i, self._properties['attribute_space'][int(i)]] )
##                            print( 'Node: %s\tAttributes: %s' % ( i, self._properties['attribute_space'][int(i)] ) )
                        except:
                            print( 'Node %s not in graph.  Skipping...' % i )
                    print( tabulate( entries, headers='firstrow' ) )
                            
                elif cmdline[1] == 'neighbors':
                    entries = [ ['Node','Neighbors'] ]
                    for i in mylist:
                        try:
                            entries.append( [i, sorted( list( self.get_neighbors(int(i))) )] )
##                            print( 'Node: %s\tNeighbors: %s' % ( i, sorted( list( self.get_neighbors(int(i))) ) ) )
                        except:
                            print( 'Node %s not in graph.  Skipping...' % i )
                    print( tabulate( entries, headers='firstrow' ) )
                            
                elif cmdline[1] == 'types':
                    entries = [ ['Node','Type'] ]
                    for i in mylist:
                        try:
                            entries.append( [i,self._properties['types'][int(i)]] )
##                            print( 'Node: %s\tType: %s' % ( i, self._properties['types'][int(i)] ) )
                        except:
                            print( 'Node %s not in graph.  Skipping...' % i )
                    print( tabulate( entries, headers='firstrow' ) )
                            
                elif cmdline[1] == 'resistance':
                    entries = [ ['Node','Resistance'] ]
                    for i in mylist:
                        try:
                            entries.append( [i, self._properties['resistance'][int(i)]] )
##                            print( 'Node: %s\tResistance: %s' % ( i, self._properties['resistance'][int(i)] ) )
                        except:
                            print( 'Node %s not in graph.  Skipping...' % i )
                    print( tabulate( entries, headers='firstrow' ) )
                            
                elif cmdline[1] == 'weights':
                    for i in mylist:
                        print( 'Node: %s' % i )
                        entries = [ ['Edge','Weight'] ]
                        nbrs = sorted( list( self.get_neighbors( int(i) ) ) )
                        for j in nbrs:
                            try:
                                entries.append( ['[%s]-->[%s]' % (j,i), self._properties['weights'][j][int(i)]] )
##                                print( '\t[%s]-->[%s] weight: %s' % ( j, i, self._properties['weights'][j][int(i)] ) )
                            except:
                                print( 'Node %s not in graph.  Skipping...' % i )
                        print( tabulate( entries, headers='firstrow' ) + '\n' )
                                
                elif cmdline[1] == 'normalized_weights':
                    for i in mylist:
                        print( 'Node: %s' % i )
                        entries = [ ['Edge','Normalized Weight'] ]
                        nbrs = sorted( list( self.get_neighbors( int(i) ) ) )
                        for j in nbrs:
                            try:
                                entries.append( ['[%s]-->[%s]' % (j,i), self._properties['normalized_weights'][j][int(i)]] )
##                                print( '\t[%s]-->[%s] normalized weight: %s' % ( j, i, self._properties['normalized_weights'][j][int(i)] ) )
                            except:
                                print( 'Node %s not in graph.  Skipping...' % i )
                        print( tabulate( entries, headers='firstrow' ) + '\n' )
                                
                elif cmdline[1] == 'masks':
                    for i in mylist:
                        print( 'Node: %s' % i )
                        entries = [ ['Neighbor','Perceived Opinion'] ]
                        nbrs = sorted( list( self.get_neighbors( int(i) ) ) )
                        for j in nbrs:
                            try:
                                entries.append( [j, self._properties['masks'][int(i)][j]] )
##                                print( '\tPerception of %d: %s' % ( j, self._properties['masks'][int(i)][j] ) )
                            except:
                                print( 'Node %s not in graph.  Skipping...' % i )
                        print( tabulate( entries, headers='firstrow' ) + '\n' )
                                
                elif cmdline[1] == 'reward':
                    node = int( cmdline[2] )
                    print( 'Node: %s' % node )
                    entries = [['Parent','Reward']]
                    if len(cmdline) > 3: parents = [ int(i) for i in cmdline[3:] ]
                    else: parents = sorted( list( self.get_neighbors( node ) ) )
                    for parent in parents:
                        if parent in sorted( list( self.get_neighbors( node ) ) ):
                            entries.append( [parent,self.get_reward_for_neighbor( node, parent )] )
##                            print( 'Node %d reward from edge [%d]-->[%d]: %f' % ( node, parent, node, self.get_reward_for_neighbor( node, parent ) ) )
                        else:
                            print( 'No edge [%d]-->[%d]' % ( parent, node ) )
                    print( tabulate( entries, headers='firstrow' ) )

                elif cmdline[1] == 'density':
                    print( 'Density: %s' % nx.density( self._graph ) )
                        
                elif cmdline[1] == 'local_average':
                    for i in mylist:
                        print( 'Average opinion in neighborhood of %s: %s' % ( int(i), self.get_local_average( int(i) ) ) )

                elif cmdline[1] == 'global_average':
                    print( 'Global average: %s' % self.get_global_average() )

                elif cmdline[1] == 'type_average':
                    if cmdline[2] not in set( [t for t in self._properties['type_dist']] ):
                        print( '[%s] is not a known type.' % cmdline[2] )
                    else:
                        print( 'Type average for [%s]: %s' % ( cmdline[2], self.get_global_average( t=cmdline[2] ) ) )

                else:
                    if cmdline[1] in self._properties:
                        print( 'Property: %s' % cmdline[1] )
                        print( self._properties[ cmdline[1] ] )
                    else:
                        print( 'No known property [%s].' % cmdline[1] )

            ## Set individual or group data values
            elif cmdline[0] == 'set':
                if cmdline[1] == 'type':
                    if cmdline[3] not in set( [t for t in self._properties['type_dist']] ):
                        print( '[%s] is not a known type.' % cmdline[3] )
                    else:
                        self._properties['indexes_by_type'][self._properties['types'][int(cmdline[2])]].remove( int(cmdline[2]) )
                        self._properties['indexes_by_type'][cmdline[3]].append( int(cmdline[2]) )
                        self._properties['types'][int(cmdline[2])] = cmdline[3]
                        print( 'Set type of node %s to: %s' % ( cmdline[2], cmdline[3] ) )
                if cmdline[1] == 'resistance':
                    if len(cmdline) == 3:
                        if 0 > float( cmdline[2] ) or 1 < float( cmdline[2] ):
                            print( 'Resistance values must fall between 0 and 1.' )
                            continue
                        for i in range( self._properties['n'] ):
                            self._properties['resistance'][i] = float( cmdline[2] )
                        print( 'Set all resistance values to: %s' % cmdline[2] )
                    if len(cmdline) == 4:
                        if 0 > float( cmdline[3] ) or 1 < float( cmdline[3] ):
                            print( 'Resistance values must fall between 0 and 1.' )
                            continue
                        try:
                            int( cmdline[2] )
                            try:
                                self._properties['resistance'][int(cmdline[2])] = float(cmdline[3])
                                print( 'Set resistance value for node %s to: %s' % ( cmdline[2], cmdline[3] ) )
                            except:
                                print( 'Node %s not in graph.  Skipping...' % cmdline[2] )
                        except:
                            if cmdline[2] not in set( [t for t in self._properties['type_dist']] ):
                                print( '[%s] is not a known type.' % cmdline[2] )
                            idxs = self._properties['indexes_by_type'][cmdline[2]]
                            for i in idxs:
                                self._properties['resistance'][i] = float( cmdline[3] )
                            print( 'Set all resistance values for nodes of type [%s] to: %s' % ( cmdline[2], cmdline[3] ) )

            ## Destroy an edge
            elif cmdline[0] == 'disconnect':
                self.disconnect( int(cmdline[1]), int(cmdline[2]) )
                print( 'Destroyed edge: [%s]-->[%s]' % (cmdline[1], cmdline[2]) )

            ## Create an edge
            elif cmdline[0] == 'connect':
                self.connect( int(cmdline[1]), int(cmdline[2]) )
                print( 'Created edge: [%s]-->[%s]' % (cmdline[1], cmdline[2]) )

            ## Reveal a topic from one node to another
            elif cmdline[0] == 'reveal':
                node1 = int(cmdline[1])
                node2 = int(cmdline[2])
                topic = int(cmdline[3])
                if node1 not in list( self.get_neighbors(node2) ):
                    print( 'Nodes %d and %d are not connected.' % ( node1, node2 ) )
                    continue
                self._properties['masks'][node2][node1][topic] = \
                            self._properties['attribute_space'][node1][topic]
                print( 'Node %s revealed topic %s to node %s' % ( node1, topic, node2 ) )

            ## Hide a topic from one topic to another
            elif cmdline[0] == 'hide':
                node1 = int(cmdline[1])
                node2 = int(cmdline[2])
                topic = int(cmdline[3])
                if node1 not in list( self.get_neighbors(node2) ):
                    print( 'Nodes %d and %d are not connected.' % ( node1, node2 ) )
                    continue
                self._properties['masks'][node2][node1][topic] = 0.
                print( 'Node %s hid topic %s from node %s' % ( node1, topic, node2 ) )

            ## Save the current graph to a specified filename
            elif cmdline[0] == 'save':
                try:
                    self._save( cmdline[1] )
                except:
                    print( 'Problem saving file: %s' % cmdline[1] )
            else:
                if cmdline[0] != 'q' and not frominherited:
                    print( 'No known command: [%s].' % cmdline[0] )

            if frominherited: return

        print( 'Exiting debugger.' )
        return

## METHODS
## __init__()
## _log( message )
## _build()
## _read( filename )
## _save( filename )
## _validate_input( props )
## generate_edges()
## initialize_edge_weights()
## initialize_attribute_space()
## initialize_correlations()
## initialize_masks()
## mix_network()
## get_neighbors( node )
## update_weight_column( node )
## get_local_average( node )
## get_global_average()
## get_reward_for_neighbor( node1, node2 )
## get_reward_for_node( node )
## connect( node1, node2 )
## disconnect( node1, node2 )
## reveal()
## hide()
## step()
## update_attributes()
## act()
## network_effects()
## track_stat()
