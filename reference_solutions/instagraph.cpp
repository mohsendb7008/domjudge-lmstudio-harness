#include<iostream>
#include<set>
#include<vector>
using namespace std;
typedef pair<int,int> ii;

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int n, m; cin >> n >> m;
    set<ii> edges;
    vector<vector<int>> g(n);
    for(int i = 0; i < m; ++i) {
        int a, b; cin >> b >> a; a--; b--;
        g[a].push_back(b);
        edges.insert(ii(a, b));
    }
    int bst = 0, val = 0;
    for(int i = 0; i < n; ++i) {
        int cur = 0;
        for(int j : g[i])
            if(!edges.count(ii(j, i)))
                cur++;
        if(cur > val) {
            bst = i;
            val = cur;
        }
    }
    cout << bst + 1 << ' ' << val << '\n';
}
